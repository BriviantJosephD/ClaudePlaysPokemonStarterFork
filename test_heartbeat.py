"""Unit tests for the emulator heartbeat watchdog.

Run with: python3 test_heartbeat.py

These tests construct a SimpleAgent-like shim with a stub emulator so we
can exercise the watchdog in isolation — no PyBoy, no Anthropic SDK, no
ROM required. We exercise _record_heartbeat and _reset_emulator directly
on a stripped-down instance built via ``object.__new__`` so __init__'s
emulator/network setup never runs.
"""

import os
import sys
import types
from collections import deque

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

# Stub out heavy optional deps so we can import agent.simple_agent in a
# CI environment that hasn't installed pyboy / anthropic / PIL. We only
# exercise the watchdog logic, which doesn't touch any of these modules.
def _install_stub(name, **attrs):
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


_install_stub("anthropic", Anthropic=lambda *a, **kw: None)
_install_stub("pyboy", PyBoy=lambda *a, **kw: None)
# PIL is imported as `from PIL import Image, ImageDraw` inside emulator.py;
# simple_agent.py doesn't import PIL directly, but the agent.emulator chain
# does. We stub the parent + submodules.
_install_stub("PIL")
_install_stub("PIL.Image")
_install_stub("PIL.ImageDraw")
sys.modules["PIL"].Image = sys.modules["PIL.Image"]
sys.modules["PIL"].ImageDraw = sys.modules["PIL.ImageDraw"]

# Import-only — we do NOT construct SimpleAgent via its normal __init__
# (that would require PyBoy + ROM + Anthropic client). Instead we build a
# bare instance and attach the watchdog state by hand.
import config
from agent import simple_agent


class StubEmulator:
    """Minimal stand-in for agent.emulator.Emulator.

    ``screenshot_hash`` returns whatever caller stuffs into ``next_hash``.
    ``reinitialize`` and ``load_state`` set flags so tests can assert the
    recovery path actually fires.
    """

    def __init__(self):
        self.next_hash = "0" * 40
        self.reinitialized = False
        self.loaded_state = None

    def screenshot_hash(self):
        return self.next_hash

    def reinitialize(self):
        self.reinitialized = True

    def load_state(self, path):
        self.loaded_state = path


def _make_agent(window=5, enabled=True, latest_save=None):
    """Build a SimpleAgent shim without touching __init__'s heavy deps."""
    # Override config knobs for this test run so we control the window
    # without needing to edit config.py.
    config.EMULATOR_HEARTBEAT_ENABLED = enabled
    config.EMULATOR_HEARTBEAT_WINDOW = window
    # Re-bind the module-level constants the agent imported at module load.
    simple_agent.EMULATOR_HEARTBEAT_ENABLED = enabled
    simple_agent.EMULATOR_HEARTBEAT_WINDOW = window

    agent = object.__new__(simple_agent.SimpleAgent)
    agent.emulator = StubEmulator()
    agent._hash_window = deque(maxlen=window)
    agent._pressed_window = deque(maxlen=window)
    agent._latest_save_path = latest_save
    agent._heartbeat_resets = 0
    return agent


def test_disabled_never_triggers():
    agent = _make_agent(window=3, enabled=False)
    agent.emulator.next_hash = "frozen"
    for _ in range(10):
        assert agent._record_heartbeat(True) is False
    assert agent._heartbeat_resets == 0


def test_short_window_no_trigger():
    # Need full window before any verdict.
    agent = _make_agent(window=5)
    agent.emulator.next_hash = "frozen"
    for _ in range(4):
        assert agent._record_heartbeat(True) is False


def test_full_window_all_frozen_with_presses_triggers():
    agent = _make_agent(window=5)
    agent.emulator.next_hash = "frozen"
    triggered = False
    for _ in range(5):
        if agent._record_heartbeat(True):
            triggered = True
    assert triggered, "expected watchdog to fire after 5 identical frames + presses"


def test_frozen_screen_without_button_presses_does_not_trigger():
    # Model wait — no presses emitted. A static screen here is legitimate
    # (e.g. waiting for text scroll), so the watchdog must NOT reset.
    agent = _make_agent(window=5)
    agent.emulator.next_hash = "frozen"
    for _ in range(10):
        assert agent._record_heartbeat(False) is False


def test_partial_presses_in_window_still_triggers():
    # Even one press in the window means the screen *should* have changed
    # at least once. If it didn't, that's a hang.
    agent = _make_agent(window=5)
    agent.emulator.next_hash = "frozen"
    # 4 no-press, 1 press — still hung.
    presses = [False, False, False, False, True]
    fired = False
    for p in presses:
        if agent._record_heartbeat(p):
            fired = True
    assert fired


def test_changing_screen_never_triggers():
    agent = _make_agent(window=5)
    # Hashes alternate — emulator is alive.
    for i in range(20):
        agent.emulator.next_hash = f"hash_{i}"
        assert agent._record_heartbeat(True) is False


def test_reset_clears_window():
    # After a reset, the window should be empty so the next set of samples
    # starts from scratch. Otherwise one hang would cascade into repeat
    # resets every single subsequent step.
    agent = _make_agent(window=3, latest_save=None)
    agent.emulator.next_hash = "frozen"
    for _ in range(3):
        agent._record_heartbeat(True)
    # Should be primed to fire — but _record_heartbeat returns True; the
    # run loop is responsible for calling _reset_emulator. Exercise that.
    agent._reset_emulator()
    assert agent.emulator.reinitialized
    assert len(agent._hash_window) == 0
    assert len(agent._pressed_window) == 0
    assert agent._heartbeat_resets == 1


def test_reset_reloads_existing_save(tmp_path=None):
    # Create a dummy save file so the recovery path exercises load_state.
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".state", delete=False) as f:
        f.write(b"fake state bytes")
        save_path = f.name
    try:
        agent = _make_agent(window=3, latest_save=save_path)
        agent._reset_emulator()
        assert agent.emulator.reinitialized
        assert agent.emulator.loaded_state == save_path
    finally:
        os.remove(save_path)


def test_reset_skips_missing_save():
    # Save path set but file no longer exists — don't crash, just log.
    agent = _make_agent(window=3, latest_save="/nonexistent/path.state")
    agent._reset_emulator()
    assert agent.emulator.reinitialized
    assert agent.emulator.loaded_state is None


def test_screenshot_hash_failure_does_not_crash():
    # Watchdog must be defensive — a hash failure should NOT take down
    # the run loop.
    agent = _make_agent(window=3)

    class BoomEmu(StubEmulator):
        def screenshot_hash(self):
            raise RuntimeError("simulated emulator hash failure")

    agent.emulator = BoomEmu()
    # Should return False (no verdict) rather than raise.
    assert agent._record_heartbeat(True) is False


if __name__ == "__main__":
    tests = [
        test_disabled_never_triggers,
        test_short_window_no_trigger,
        test_full_window_all_frozen_with_presses_triggers,
        test_frozen_screen_without_button_presses_does_not_trigger,
        test_partial_presses_in_window_still_triggers,
        test_changing_screen_never_triggers,
        test_reset_clears_window,
        test_reset_reloads_existing_save,
        test_reset_skips_missing_save,
        test_screenshot_hash_failure_does_not_crash,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(0 if failed == 0 else 1)
