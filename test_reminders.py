"""Unit tests for the helpful-reminders rules.

Run with: python3 test_reminders.py

Imports the standalone ``agent.reminders`` module (no Anthropic SDK or
PyBoy dependencies) so tests run in any environment that has stdlib only.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

from agent.reminders import compute_helpful_reminders


def test_empty_inputs_no_reminders():
    out = compute_helpful_reminders("", "", "")
    assert out == [], f"expected [], got {out!r}"


def test_low_hp_in_party_section_triggers_pokecenter_reminder():
    memory = (
        "Player: ASH\n"
        "Pokemon Party:\n"
        "WARTORTLE (WARTORTLE):\n"
        "Level 20 - HP: 4/30\n"
    )
    out = compute_helpful_reminders(memory, None, "Pressed buttons: a")
    assert any("PokeCenter" in r for r in out), f"expected PokeCenter reminder, got {out!r}"


def test_low_hp_outside_party_does_not_trigger():
    # Anything before the "Pokemon Party:" header is ignored. Future enemy
    # HP fields must not produce a "visit PokeCenter" reminder.
    memory = (
        "Enemy Pokemon:\nHP: 1/50\n"
        "Pokemon Party:\nWARTORTLE\nLevel 20 - HP: 28/30\n"
    )
    out = compute_helpful_reminders(memory, None, "")
    assert not any("PokeCenter" in r for r in out), f"unexpected PokeCenter reminder: {out!r}"


def test_healthy_party_no_pokecenter_reminder():
    memory = "Pokemon Party:\nWARTORTLE\nLevel 20 - HP: 28/30"
    out = compute_helpful_reminders(memory, None, "")
    assert not any("PokeCenter" in r for r in out), f"unexpected PokeCenter reminder: {out!r}"


def test_fainted_does_not_trigger_low_hp():
    # cur == 0 means fainted — that's a different reminder family, so the
    # low-HP rule must NOT fire on a HP: 0/X line alone.
    memory = "Pokemon Party:\nCHARIZARD\nLevel 30 - HP: 0/100"
    out = compute_helpful_reminders(memory, None, "")
    assert not any("PokeCenter" in r for r in out), f"fainted-only should not trigger low HP: {out!r}"


def test_dialog_present_triggers_reminder():
    memory = "Dialog: Hello, I'm Professor Oak!"
    out = compute_helpful_reminders(memory, None, "")
    assert any("dialog" in r.lower() for r in out), f"expected dialog reminder, got {out!r}"


def test_dialog_none_does_not_trigger():
    # The emulator emits "Dialog: None" when no dialog is active; the rule
    # must not trip on that sentinel.
    memory = "Dialog: None\nPokemon Party:\nWARTORTLE\nLevel 20 - HP: 28/30"
    out = compute_helpful_reminders(memory, None, "")
    assert not any("dialog" in r.lower() for r in out), f"unexpected dialog reminder: {out!r}"


def test_battle_state_triggers_reminder():
    memory = "In Battle\nEnemy Pokemon: PIDGEY\nLevel 5"
    out = compute_helpful_reminders(memory, None, "")
    assert any("battle" in r.lower() for r in out), f"expected battle reminder, got {out!r}"


def _build_collision_map(walls):
    """Helper: build a synthetic collision map with walls at given (row, col) cells."""
    rows = []
    for r in range(9):
        chars = []
        for c in range(10):
            if r == 4 and c == 4:
                chars.append("→")  # player arrow
            elif (r, c) in walls:
                chars.append("█")  # full block (wall)
            else:
                chars.append("·")  # middle dot (path)
        rows.append("|" + "".join(chars) + "|")
    border = "+" + "-" * 10 + "+"
    return "\n".join([border] + rows + [border])


def test_narrow_passage_three_walls():
    walls = {(3, 4), (5, 4), (4, 3)}  # only (4, 5) open
    out = compute_helpful_reminders("", _build_collision_map(walls), "")
    assert any("narrow passage" in r.lower() for r in out), f"expected narrow-passage, got {out!r}"


def test_open_terrain_no_narrow_reminder():
    out = compute_helpful_reminders("", _build_collision_map(set()), "")
    assert not any("narrow passage" in r.lower() for r in out), f"unexpected narrow-passage: {out!r}"


def test_navigation_failed_action_summary():
    out = compute_helpful_reminders("", None, "Navigation failed: target unreachable")
    assert any("navigation failed" in r.lower() for r in out), f"expected nav-fail reminder, got {out!r}"


def test_malformed_inputs_do_not_raise():
    out = compute_helpful_reminders(None, None, None)
    assert out == [], f"expected [] for all-None, got {out!r}"
    out = compute_helpful_reminders(12345, [1, 2], object())
    assert isinstance(out, list), f"expected list, got {type(out)}"


def test_low_hp_dedup():
    memory = (
        "Pokemon Party:\n"
        "MON1\nLevel 5 - HP: 1/20\n"
        "MON2\nLevel 5 - HP: 2/30\n"
        "MON3\nLevel 5 - HP: 5/100\n"
    )
    out = compute_helpful_reminders(memory, None, "")
    pokecenter_count = sum(1 for r in out if "PokeCenter" in r)
    assert pokecenter_count == 1, f"expected 1 PokeCenter reminder, got {pokecenter_count}: {out!r}"


if __name__ == "__main__":
    tests = [
        test_empty_inputs_no_reminders,
        test_low_hp_in_party_section_triggers_pokecenter_reminder,
        test_low_hp_outside_party_does_not_trigger,
        test_healthy_party_no_pokecenter_reminder,
        test_fainted_does_not_trigger_low_hp,
        test_dialog_present_triggers_reminder,
        test_dialog_none_does_not_trigger,
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
