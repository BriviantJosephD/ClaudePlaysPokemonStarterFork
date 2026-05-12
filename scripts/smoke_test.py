#!/usr/bin/env python3
"""Agent-loop smoke test: 5 steps, real ROM, real API calls.

Verifies the plumbing between Claude, the emulator, and the reminders engine.
This is NOT a quality test — we don't assert anything about gameplay; we only
confirm that on each step:

  * a screenshot was captured (non-empty PIL image)
  * a collision overlay image was generated (or explicitly None pre-overworld)
  * the RAM memory readout populated
  * the reminders engine produced output (list, possibly empty)
  * at least one tool call dispatched correctly

Bounded to 5 steps. Should complete in under ~60s on a working setup.
Use before pushing changes that touch the agent loop:

    make smoke
    # or
    python scripts/smoke_test.py --rom pokemon.gb

Exits 0 on success, 1 on plumbing failure, 2 on skip (ROM missing or API key
missing). API spend is real but tiny — five turns, ~$0.30 at default config.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import logging  # noqa: E402

# Reduce log noise — the agent itself logs verbosely on INFO. We print our own
# per-step status lines and want them legible.
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


SMOKE_STEPS = 5
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_SKIP = 2


def _fail(reason: str) -> int:
    print(f"SMOKE FAIL: {reason}", file=sys.stderr)
    return EXIT_FAIL


def _skip(reason: str) -> int:
    print(f"SMOKE SKIP: {reason}")
    return EXIT_SKIP


def _capture_tool_calls(agent):
    """Wrap agent.process_tool_call to count dispatches per step.

    We want to assert "at least one tool call dispatched correctly" per step
    without re-implementing the agent loop. Easiest way: shim the method,
    record names and exceptions, then restore.
    """
    original = agent.process_tool_call
    state = {"calls": []}

    def wrapped(tool_call):
        try:
            result = original(tool_call)
            state["calls"].append((tool_call.name, None))
            return result
        except Exception as e:  # noqa: BLE001 — record and re-raise
            state["calls"].append((tool_call.name, e))
            raise

    agent.process_tool_call = wrapped  # type: ignore[method-assign]
    return state


def _verify_observation(agent) -> tuple[bool, str]:
    """Pull a fresh observation from the emulator and check the plumbing.

    Returns (ok, reason). All four signals are checked even on failure so
    the operator sees every broken piece in one run, not just the first.
    """
    from agent.reminders import compute_helpful_reminders  # noqa: WPS433

    failures = []

    try:
        screenshot = agent.emulator.get_screenshot()
        if screenshot is None or screenshot.size[0] == 0 or screenshot.size[1] == 0:
            failures.append("screenshot empty")
    except Exception as e:  # noqa: BLE001
        failures.append(f"screenshot raised {type(e).__name__}: {e}")

    # Overlay can legitimately be None pre-overworld (title screen, intro
    # cutscene). We only fail if the call itself raises.
    try:
        agent.emulator.get_collision_overlay_image()
    except Exception as e:  # noqa: BLE001
        failures.append(f"overlay raised {type(e).__name__}: {e}")

    try:
        memory_info = agent.emulator.get_state_from_memory()
        if not memory_info or not memory_info.strip():
            failures.append("memory readout empty")
    except Exception as e:  # noqa: BLE001
        memory_info = ""
        failures.append(f"memory raised {type(e).__name__}: {e}")

    try:
        collision = agent.emulator.get_collision_map()
    except Exception:  # noqa: BLE001 — collision can be None pre-overworld
        collision = None

    try:
        reminders = compute_helpful_reminders(memory_info, collision, "")
        # The reminders engine must return a list (possibly empty). None or a
        # non-iterable means the engine itself is broken.
        if not isinstance(reminders, list):
            failures.append(f"reminders returned {type(reminders).__name__}, expected list")
    except Exception as e:  # noqa: BLE001
        failures.append(f"reminders raised {type(e).__name__}: {e}")

    if failures:
        return False, "; ".join(failures)
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--rom",
        default=str(REPO_ROOT / "pokemon.gb"),
        help="Path to the Pokemon Red ROM (default: pokemon.gb at repo root)",
    )
    args = parser.parse_args()

    rom_path = Path(args.rom)
    if not rom_path.is_absolute():
        rom_path = (REPO_ROOT / rom_path).resolve()

    if not rom_path.is_file():
        return _skip(f"ROM not present at {rom_path}; place pokemon.gb or pass --rom")

    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return _skip("ANTHROPIC_API_KEY not set; export it before running smoke test")

    # Import the agent only after the skips so missing optional deps during a
    # SKIP path don't masquerade as failures.
    try:
        from agent import simple_agent as _simple_agent_mod  # noqa: WPS433
        SimpleAgent = _simple_agent_mod.SimpleAgent
    except Exception as e:  # noqa: BLE001
        return _fail(f"import SimpleAgent: {type(e).__name__}: {e}")

    # Disable the heartbeat watchdog for the duration of the smoke test. The
    # smoke runs from the boot screen with only five button-press turns, so a
    # legitimate intro-cutscene "stall" could otherwise look like a hang and
    # trip the reset path. Patching the module-level binding (not config) is
    # required because simple_agent.py captures EMULATOR_HEARTBEAT_ENABLED at
    # import time via `from config import ...`.
    _simple_agent_mod.EMULATOR_HEARTBEAT_ENABLED = False

    print(f"SMOKE START: rom={rom_path} steps={SMOKE_STEPS}")

    try:
        agent = SimpleAgent(
            rom_path=str(rom_path),
            headless=True,
            sound=False,
            max_history=60,  # high — we don't want summarization to fire in 5 steps
        )
    except Exception as e:  # noqa: BLE001
        return _fail(f"SimpleAgent init: {type(e).__name__}: {e}")

    tool_state = _capture_tool_calls(agent)
    failures: list[str] = []

    try:
        for step in range(1, SMOKE_STEPS + 1):
            calls_before = len(tool_state["calls"])
            try:
                completed = agent.run(num_steps=1)
            except Exception as e:  # noqa: BLE001
                failures.append(f"step {step}: agent.run raised {type(e).__name__}: {e}")
                break

            if completed != 1:
                failures.append(f"step {step}: agent.run completed {completed} steps, expected 1")

            calls_this_step = tool_state["calls"][calls_before:]
            if not calls_this_step:
                failures.append(f"step {step}: no tool call dispatched")
            else:
                failed_calls = [(n, e) for n, e in calls_this_step if e is not None]
                if failed_calls:
                    names = ", ".join(f"{n}({type(e).__name__})" for n, e in failed_calls)
                    failures.append(f"step {step}: tool dispatch errors: {names}")

            ok, reason = _verify_observation(agent)
            if not ok:
                failures.append(f"step {step}: {reason}")

            status = "OK" if ok and calls_this_step else "FAIL"
            tools = ",".join(n for n, _ in calls_this_step) or "none"
            print(f"  step {step}/{SMOKE_STEPS}: {status} tools=[{tools}]")
    finally:
        try:
            agent.stop()
        except Exception as e:  # noqa: BLE001
            # Stop failure is not a smoke failure per se, but it's worth noting.
            print(f"WARNING: agent.stop raised {type(e).__name__}: {e}", file=sys.stderr)

    if failures:
        print()
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return _fail(f"{len(failures)} plumbing issue(s); see above")

    print(f"\nSMOKE PASSED: {SMOKE_STEPS} steps, {len(tool_state['calls'])} tool calls.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
