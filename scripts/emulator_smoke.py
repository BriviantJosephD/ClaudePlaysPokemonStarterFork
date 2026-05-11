#!/usr/bin/env python3
"""Smoke-test the emulator + ROM setup WITHOUT spending API tokens.

The full agent loop requires an Anthropic API key. Sometimes you only need
to verify the *non-LLM* half of the stack — ROM loads, PyBoy boots,
screenshots come back, the memory reader produces output, the collision
map and walkability overlay render. This script does exactly that and
nothing more.

Run with:
    python3 scripts/emulator_smoke.py --rom roms/pokemon_red.gb
or:
    make emulator-smoke ROM=roms/pokemon_red.gb

Exits 0 if every step succeeds, non-zero otherwise. Writes a small set of
artifacts (screenshot.png, overlay.png, test.state) to a temp directory and
prints the path so you can inspect the visuals.
"""

import argparse
import os
import sys
import tempfile

# Make `from agent.emulator import Emulator` work whether the script is
# invoked directly or via `make emulator-smoke`.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from agent.emulator import Emulator  # noqa: E402 — sys.path mutation above


def _step(n, total, label):
    print(f"[{n}/{total}] {label}...")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--rom",
        default="pokemon.gb",
        help="Path to the Game Boy ROM file (default: pokemon.gb)",
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Show the emulator window (default: headless)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.rom):
        print(f"ERROR: ROM not found at {args.rom!r}.", file=sys.stderr)
        print("       Pass --rom PATH or place pokemon.gb in the repo root.", file=sys.stderr)
        sys.exit(2)

    artifacts_dir = tempfile.mkdtemp(prefix="emulator_smoke_")
    total = 7

    try:
        _step(1, total, f"Loading ROM ({args.rom})")
        emulator = Emulator(args.rom, headless=not args.display, sound=False)
        emulator.initialize()
        print("      OK")

        _step(2, total, "Capturing screenshot")
        screenshot = emulator.get_screenshot()
        screen_path = os.path.join(artifacts_dir, "screenshot.png")
        screenshot.save(screen_path)
        print(f"      OK — {screenshot.size} {screenshot.mode}, wrote {screen_path}")

        _step(3, total, "Reading RAM state")
        memory_info = emulator.get_state_from_memory()
        lines = memory_info.splitlines() if memory_info else []
        if not lines:
            raise RuntimeError("get_state_from_memory returned empty output")
        print(f"      OK — {len(lines)} lines; first 3:")
        for line in lines[:3]:
            print(f"        {line}")

        _step(4, total, "Building collision map")
        collision_map = emulator.get_collision_map()
        if collision_map:
            print(f"      OK — {len(collision_map.splitlines())} lines")
        else:
            # The downsampler returns None when it can't find the player
            # direction (e.g. during the opening title screen before the
            # player exists on the map). Not a failure for this smoke test.
            print("      none — likely pre-overworld; not a failure")

        _step(5, total, "Rendering walkability overlay")
        overlay = emulator.get_collision_overlay_image()
        if overlay is not None:
            overlay_path = os.path.join(artifacts_dir, "overlay.png")
            overlay.save(overlay_path)
            print(f"      OK — {overlay.size} {overlay.mode}, wrote {overlay_path}")
        else:
            print("      none — overlay needs an in-overworld direction; not a failure")

        _step(6, total, "Pressing test buttons (a, b, start, select)")
        for btn in ("a", "b", "start", "select"):
            emulator.press_buttons([btn], wait=False)
        print("      OK — no crash")

        _step(7, total, "Save/load state roundtrip")
        state_path = os.path.join(artifacts_dir, "test.state")
        emulator.save_state(state_path)
        if not os.path.exists(state_path):
            raise RuntimeError("save_state did not produce a file")
        emulator.load_state(state_path)
        size_kb = os.path.getsize(state_path) / 1024
        print(f"      OK — {size_kb:.1f} KB at {state_path}")

    except Exception as e:
        print(f"\nSMOKE FAILED at step: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            emulator.stop()
        except Exception:
            pass

    print()
    print("SMOKE PASSED — emulator + ROM stack is healthy.")
    print(f"Artifacts: {artifacts_dir}")
    print("  Open screenshot.png and overlay.png to confirm visuals look right.")
    print("  Delete the directory when done; nothing in it is needed for the agent.")


if __name__ == "__main__":
    main()
