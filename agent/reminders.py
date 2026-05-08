"""Situational helpful-reminder rules for use_emulator tool results.

Imported by ``agent.simple_agent`` and by the test suite. Kept in its own
module — with no Anthropic SDK or PyBoy imports — so unit tests can exercise
the rule logic without booting the full agent stack.

Each rule is wrapped in its own try/except so a single bad pattern-match
cannot suppress the others. False positives are worse than no reminder
(they waste context tokens), so triggers are deliberately conservative.
"""

import logging
import re

logger = logging.getLogger(__name__)

# Matches "HP: <cur>/<max>" allowing whitespace and arbitrary leading chars.
_HP_PATTERN = re.compile(r"HP:\s*(\d+)\s*/\s*(\d+)", re.IGNORECASE)
# Matches a Dialog line like "Dialog: <text>" (the only emitter today).
_DIALOG_PATTERN = re.compile(r"^\s*Dialog\s*[:=]\s*(.*)$", re.IGNORECASE | re.MULTILINE)
# Header marking the start of the party-Pokemon section in memory_info.
_PARTY_HEADER = re.compile(r"Pokemon Party\s*:?", re.IGNORECASE)


def compute_helpful_reminders(memory_info, collision_map, action_summary):
    """Return 0-N short situational reminder strings for the current state.

    Args:
        memory_info: The RAM-state string from ``Emulator.get_state_from_memory()``.
        collision_map: The 9x10 ASCII map from ``Emulator.get_collision_map()``,
            or None if the map is unavailable this turn.
        action_summary: Short string describing what just happened, used for
            navigation-failure detection.

    Returns:
        A list of reminder strings (possibly empty). Never raises.
    """
    reminders = []

    # 1) Low-HP warning: scan ONLY the "Pokemon Party:" section so any future
    # enemy-HP fields elsewhere in memory_info cannot trigger a "visit a
    # PokeCenter" reminder when the player is actually winning. Fires once
    # if any party member is below 25% of max and not fainted.
    try:
        if isinstance(memory_info, str):
            party_match = _PARTY_HEADER.search(memory_info)
            party_text = memory_info[party_match.end():] if party_match else ""
            for cur_s, max_s in _HP_PATTERN.findall(party_text):
                cur = int(cur_s)
                cap = int(max_s)
                # cur > 0 excludes fainted Pokemon, which need a different
                # reminder (Revive / switch) — not "visit a PokeCenter".
                if cap > 0 and cur > 0 and (cur / cap) < 0.25:
                    reminders.append(
                        "Party HP is low — consider visiting a PokeCenter "
                        "before the next battle."
                    )
                    break
    except Exception as e:  # noqa: BLE001 — defensive; rule must not crash
        logger.debug(f"[Reminders] HP rule failed: {e}")

    # 2) Battle context: trust explicit RAM markers only, not screenshot guesses.
    try:
        if isinstance(memory_info, str):
            lower = memory_info.lower()
            if any(k in lower for k in ("in battle", "battle:", "enemy pokemon", "enemy pokémon")):
                reminders.append(
                    "You are in a battle. Type matchups matter — check your "
                    "knowledge base for the opponent's weaknesses before attacking."
                )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[Reminders] Battle rule failed: {e}")

    # 3) Active dialog: guard against arrow keys mid-text.
    # The emulator emits "Dialog: None" when no dialog is active, so we
    # explicitly exclude that sentinel rather than treating it as content.
    try:
        if isinstance(memory_info, str):
            match = _DIALOG_PATTERN.search(memory_info)
            if match:
                body = match.group(1).strip()
                if body and body.lower() != "none":
                    reminders.append(
                        "A dialog box is active. Press 'a' to advance text. "
                        "Avoid pressing arrow keys mid-dialog — they can change "
                        "menu cursor unintentionally."
                    )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[Reminders] Dialog rule failed: {e}")

    # 4) Narrow passage: count walls in the four cardinal neighbors of the
    # player tile (always rendered at row 4, col 4 inside the bordered map).
    # The expected map format is a 9-row block of "|<10 chars>|" lines. If
    # the format ever changes, this rule fails closed (no reminder, no crash).
    try:
        if isinstance(collision_map, str) and collision_map:
            map_lines = [ln for ln in collision_map.splitlines() if ln.startswith("|")]
            if len(map_lines) >= 9:
                def cell(r, c):
                    line = map_lines[r]
                    idx = c + 1  # skip the leading '|'
                    return line[idx] if idx < len(line) - 1 else " "

                wall_char = "█"
                neighbors = [cell(3, 4), cell(5, 4), cell(4, 3), cell(4, 5)]
                wall_count = sum(1 for ch in neighbors if ch == wall_char)
                if wall_count >= 3:
                    reminders.append(
                        "You are in a narrow passage — only one direction "
                        "is open. Plan carefully before moving."
                    )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[Reminders] Narrow-passage rule failed: {e}")

    # 5) Navigation failure: nudge toward common root causes.
    try:
        if isinstance(action_summary, str) and "Navigation failed" in action_summary:
            reminders.append(
                "Navigation failed. Consider whether you're on the wrong floor, "
                "blocked by an NPC, or need a key item (Surf, Cut, Strength)."
            )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[Reminders] Nav-fail rule failed: {e}")

    return reminders
