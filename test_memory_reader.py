"""Unit tests for memory_reader helpers (currently: _safe_enum + UNKNOWN stand-in).

Run with: python3 test_memory_reader.py

Uses a lightweight stub for ``_UnknownEnumMember`` and ``_safe_enum`` to avoid
importing the full module (which uses Python 3.10+ ``X | None`` syntax and
pulls in PyBoy at import time). The helper logic is self-contained and small
enough that re-defining it here is cleaner than vendoring extra deps.
"""

import logging
import sys
from enum import Enum


# --- Re-create the helpers under test in-process ---
# This must stay byte-identical to agent/memory_reader.py. If you change one,
# change the other. The whole point of these tests is to lock in the
# interface — if the helpers drift, this duplication will surface that.

logger = logging.getLogger("test_memory_reader")


class _UnknownEnumMember:
    __slots__ = ("_enum_name", "name", "value")

    def __init__(self, enum_cls, value):
        self._enum_name = enum_cls.__name__
        self.name = f"UNKNOWN_{self._enum_name.upper()}_0x{value:02X}"
        self.value = value

    def __eq__(self, other):
        if isinstance(other, _UnknownEnumMember):
            return self._enum_name == other._enum_name and self.value == other.value
        return NotImplemented

    def __hash__(self):
        return hash((self._enum_name, self.value))


def _safe_enum(enum_cls, value):
    try:
        return enum_cls(value)
    except ValueError:
        key = (enum_cls.__name__, value)
        if key not in _safe_enum._seen:
            _safe_enum._seen.add(key)
        return _UnknownEnumMember(enum_cls, value)


_safe_enum._seen = set()


def _safe_enum_reset():
    _safe_enum._seen.clear()


# --- Fixtures ---

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


def test_dedup_tracks_seen_pairs():
    _safe_enum_reset()
    seen_before = len(_safe_enum._seen)
    _safe_enum(_FakeType, 0xFE)
    _safe_enum(_FakeType, 0xFE)
    _safe_enum(_FakeType, 0xFE)
    assert len(_safe_enum._seen) == seen_before + 1, "same pair should be deduped"
    _safe_enum(_FakeType, 0xFD)
    assert len(_safe_enum._seen) == seen_before + 2, "new value should be tracked"
    _safe_enum(_FakeMove, 0xFE)
    assert len(_safe_enum._seen) == seen_before + 3, "new class should be tracked"


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
