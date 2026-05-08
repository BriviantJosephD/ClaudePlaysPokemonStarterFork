"""Unit tests for the compute_helpful_reminders helper.

Run with: python3 test_reminders.py

These tests stub out import-time side effects from simple_agent (it pulls in
config + emulator on import). To stay light, we exec just the functions we
need from the module rather than importing it normally.
"""

import sys
import os
import importlib.util

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)


def _load_compute_helpful_reminders():
    """Import compute_helpful_reminders without triggering the full module's
    import-time emulator initialization. We inject a lightweight stub for the
    config import so simple_agent's top-level constants are available."""
    # Import the actual module — config exists in the repo root and emulator
    # imports lazily through PIL/pyboy. If pyboy is missing this will fail.
    try:
        from agent.simple_agent import compute_helpful_reminders  # type: ignore
    except Exception as e:
        print(f"FAILED to import compute_helpful_reminders directly: {e}")
        # Fallback: load the function source via exec from the file.
        path = os.path.join(REPO_ROOT, "agent", "simple_agent.py")
        with open(path, "r") as f:
            src = f.read()
        # Slice from the function definition to the closing 'return reminders'.
        start = src.index("def compute_helpful_reminders")
        end = src.index("\n\nSYSTEM_PROMPT")
        snippet = (
            "import re as _re\n"
            "import logging\n"
            "logger = logging.getLogger('test')\n"
            "_HP_PATTERN = _re.compile(r'HP:\\s*(\\d+)\\s*/\\s*(\\d+)', _re.IGNORECASE)\n"
            "_DIALOG_PATTERN = _re.compile(r'^\\s*Dialog\\s*[:=]\\s*(\\S.*)$', _re.IGNORECASE | _re.MULTILINE)\n"
            + src[start:end]
        )
        ns = {}
        exec(snippet, ns)
        return ns["compute_helpful_reminders"]
    return compute_helpful_reminders


compute_helpful_reminders = _load_compute_helpful_reminders()


def test_empty_inputs_no_reminders():
    out = compute_helpful_reminders("", "", "")
    assert out == [], f"expected [], got {out!r}"


def test_low_hp_triggers_pokecenter_reminder():
    memory = "Pokemon Party:\nWARTORTLE\nLevel 20 - HP: 4/30\nMoves: ..."
    out = compute_helpful_reminders(memory, None, "Pressed buttons: a")
    assert any("PokeCenter" in r for r in out), f"expected PokeCenter reminder, got {out!r}"


def test_healthy_hp_no_pokecenter_reminder():
    memory = "Pokemon Party:\nWARTORTLE\nLevel 20 - HP: 28/30"
    out = compute_helpful_reminders(memory, None, "")
    assert not any("PokeCenter" in r for r in out), f"unexpected PokeCenter reminder: {out!r}"


def test_dialog_active_triggers_reminder():
    memory = "Dialog: Hello, I'm Professor Oak!"
    out = compute_helpful_reminders(memory, None, "")
    assert any("dialog" in r.lower() for r in out), f"expected dialog reminder, got {out!r}"


def test_battle_state_triggers_reminder():
    memory = "In Battle\nEnemy Pokemon: PIDGEY\nLevel 5"
    out = compute_helpful_reminders(memory, None, "")
    assert any("battle" in r.lower() for r in out), f"expected battle reminder, got {out!r}"


def test_narrow_passage_three_walls():
    # Build a 9x10 collision map where (3,4), (5,4), (4,3) are walls and (4,5) is path.
    # Layout: col 0..9, row 0..8. Player at (4,4). We use '█' for wall, '·' for path.
    rows = []
    for r in range(9):
        row_chars = []
        for c in range(10):
            if r == 4 and c == 4:
                row_chars.append("→")  # player
            elif (r, c) in {(3, 4), (5, 4), (4, 3)}:
                row_chars.append("█")
            else:
                row_chars.append("·")
        rows.append("|" + "".join(row_chars) + "|")
    border = "+" + "-" * 10 + "+"
    collision = "\n".join([border] + rows + [border])
    out = compute_helpful_reminders("", collision, "")
    assert any("narrow passage" in r.lower() for r in out), f"expected narrow-passage reminder, got {out!r}"


def test_open_terrain_no_narrow_reminder():
    rows = []
    for r in range(9):
        row_chars = []
        for c in range(10):
            row_chars.append("→" if (r == 4 and c == 4) else "·")
        rows.append("|" + "".join(row_chars) + "|")
    border = "+" + "-" * 10 + "+"
    collision = "\n".join([border] + rows + [border])
    out = compute_helpful_reminders("", collision, "")
    assert not any("narrow passage" in r.lower() for r in out), f"unexpected narrow-passage: {out!r}"


def test_navigation_failed_action_summary():
    out = compute_helpful_reminders("", None, "Navigation failed: target unreachable")
    assert any("navigation failed" in r.lower() for r in out), f"expected nav-fail reminder, got {out!r}"


def test_malformed_inputs_do_not_raise():
    # All non-string inputs should be tolerated.
    out = compute_helpful_reminders(None, None, None)
    assert out == [], f"expected [] for all-None, got {out!r}"
    out = compute_helpful_reminders(12345, [1, 2], object())
    assert isinstance(out, list), f"expected list, got {type(out)}"


def test_low_hp_dedup():
    memory = "HP: 1/20\nHP: 2/30\nHP: 5/100"  # all three are low
    out = compute_helpful_reminders(memory, None, "")
    pokecenter_count = sum(1 for r in out if "PokeCenter" in r)
    assert pokecenter_count == 1, f"expected 1 PokeCenter reminder, got {pokecenter_count}: {out!r}"


if __name__ == "__main__":
    tests = [
        test_empty_inputs_no_reminders,
        test_low_hp_triggers_pokecenter_reminder,
        test_healthy_hp_no_pokecenter_reminder,
        test_dialog_active_triggers_reminder,
        test_battle_state_triggers_reminder,
        test_narrow_passage_three_walls,
        test_open_terrain_no_narrow_reminder,
        test_navigation_failed_action_summary,
        test_malformed_inputs_do_not_raise,
        test_low_hp_dedup,
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
