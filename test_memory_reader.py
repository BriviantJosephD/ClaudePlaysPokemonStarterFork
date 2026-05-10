"""Unit tests for ``agent.memory_reader`` helpers (currently: ``_safe_enum``
and the ``_UnknownEnumMember`` stand-in).

Run with: ``python3 test_memory_reader.py``

Imports the real helpers from ``agent.memory_reader`` so the tests pin down
production behavior — no duplicated copy that can drift. ``memory_reader``
is stdlib-only at import time (no PyBoy / numpy / PIL), so this stays cheap.
"""

import os
import sys
from enum import Enum

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

from agent.memory_reader import (  # noqa: E402 — sys.path mutation above
    _safe_enum,
    _safe_enum_reset,
    _UnknownEnumMember,
    Move,
    PokemonType,
)


# --- Fixtures: lightweight private enums avoid coupling test assertions to
# specific real Pokemon values that might be renumbered upstream. Two of the
# tests below also exercise the real Move and PokemonType enums to confirm
# the production stand-in works against them, not just the fakes.

class _FakeType(Enum):
    NORMAL = 0
    FIRE = 1
    WATER = 2


class _FakeMove(Enum):
    TACKLE = 1
    SCRATCH = 2


# --- Tests ---

def test_known_value_returns_real_enum_member():
    m = _safe_enum(_FakeType, 0)
    assert m is _FakeType.NORMAL, f"expected NORMAL, got {m!r}"


def test_unknown_value_returns_stand_in():
    u = _safe_enum(_FakeType, 0xFE)
    assert isinstance(u, _UnknownEnumMember), f"expected stand-in, got {type(u).__name__}"
    assert u.name == "UNKNOWN__FAKETYPE_0xFE", f"unexpected name: {u.name}"
    assert u.value == 0xFE, f"value not preserved: {u.value}"


def test_name_replace_underscores_works_on_stand_in():
    u = _safe_enum(_FakeType, 0xFF)
    display = u.name.replace("_", " ")
    assert "UNKNOWN" in display, f"display string broken: {display!r}"


def test_unknowns_with_same_value_and_class_are_equal():
    a = _safe_enum(_FakeType, 0xFE)
    b = _safe_enum(_FakeType, 0xFE)
    assert a == b, f"unknowns with same (class, value) should compare equal: {a!r} vs {b!r}"
    assert hash(a) == hash(b), "hashes must agree with equality"


def test_unknowns_with_different_values_are_not_equal():
    a = _safe_enum(_FakeType, 0xFE)
    b = _safe_enum(_FakeType, 0xFD)
    assert a != b, "different values should not compare equal"


def test_unknowns_with_different_classes_are_not_equal():
    # Same byte, different wrapped enum class. The collapse logic in
    # read_party_pokemon would be wrong if these matched.
    a = _safe_enum(_FakeType, 0xFE)
    b = _safe_enum(_FakeMove, 0xFE)
    assert a != b, "same value across different classes should not compare equal"


def test_eq_with_real_enum_returns_false():
    # _UnknownEnumMember.__eq__ returns NotImplemented for foreign types so
    # Python falls back to the real Enum's __eq__, which correctly says no.
    u = _safe_enum(_FakeType, 0xFE)
    assert not (u == _FakeType.NORMAL), "unknown should not equal real enum member"
    assert not (_FakeType.NORMAL == u), "real enum member should not equal unknown"


def test_real_pokemon_type_unknown_byte():
    # Exercise the production PokemonType to confirm the helper works on it,
    # not just on the lightweight fakes. 0xFE is well outside the type table.
    u = _safe_enum(PokemonType, 0xFE)
    assert isinstance(u, _UnknownEnumMember)
    assert u.name == "UNKNOWN_POKEMONTYPE_0xFE"


def test_real_move_unknown_byte():
    u = _safe_enum(Move, 0xFE)
    assert isinstance(u, _UnknownEnumMember)
    assert "UNKNOWN_MOVE" in u.name


def test_dedup_tracks_seen_pairs():
    _safe_enum_reset()
    _safe_enum(_FakeType, 0xFE)
    _safe_enum(_FakeType, 0xFE)
    _safe_enum(_FakeType, 0xFE)
    assert len(_safe_enum._seen) == 1, "same pair should be deduped"
    _safe_enum(_FakeType, 0xFD)
    assert len(_safe_enum._seen) == 2, "new value should be tracked"
    _safe_enum(_FakeMove, 0xFE)
    assert len(_safe_enum._seen) == 3, "new class should be tracked"


def test_reset_clears_seen():
    _safe_enum(_FakeType, 0xFE)
    assert len(_safe_enum._seen) > 0
    _safe_enum_reset()
    assert len(_safe_enum._seen) == 0


if __name__ == "__main__":
    tests = [
        test_known_value_returns_real_enum_member,
        test_unknown_value_returns_stand_in,
        test_name_replace_underscores_works_on_stand_in,
        test_unknowns_with_same_value_and_class_are_equal,
        test_unknowns_with_different_values_are_not_equal,
        test_unknowns_with_different_classes_are_not_equal,
        test_eq_with_real_enum_returns_false,
        test_real_pokemon_type_unknown_byte,
        test_real_move_unknown_byte,
        test_dedup_tracks_seen_pairs,
        test_reset_clears_seen,
    ]
    failed = 0
    for t in tests:
        try:
            _safe_enum_reset()
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
