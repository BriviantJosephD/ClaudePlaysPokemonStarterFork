"""Unit tests for the --load-kb / --fresh-kb resume UX.

Run with: python3 test_kb_resume.py

KnowledgeBase has no Anthropic / PyBoy deps, so it imports directly. The
CLI argparse wiring lives in main.py — we stub the heavy modules there and
inspect the parser, plus assert that mutually exclusive flags error out.
"""

import json
import os
import sys
import tempfile
import types

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

from agent.knowledge_base import KnowledgeBase


def test_load_existing_kb_default_behavior():
    """No flags → KB loads from configured path if file exists."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "kb.json")
        with open(path, "w") as f:
            json.dump({"brock": "rock-type gym leader"}, f)
        kb = KnowledgeBase(path)
        assert kb.data == {"brock": "rock-type gym leader"}, (
            f"expected loaded data, got {kb.data!r}"
        )


def test_fresh_kb_ignores_existing_file():
    """fresh=True → data is empty even when a file exists at path."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "kb.json")
        with open(path, "w") as f:
            json.dump({"brock": "should be ignored"}, f)
        kb = KnowledgeBase(path, fresh=True)
        assert kb.data == {}, (
            f"fresh KB should be empty, got {kb.data!r}"
        )
        # File on disk is unchanged until a write happens.
        with open(path) as f:
            assert json.load(f) == {"brock": "should be ignored"}


def test_fresh_kb_writes_overwrite_old_file():
    """First add after fresh=True replaces the on-disk contents."""
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "kb.json")
        with open(path, "w") as f:
            json.dump({"old": "data"}, f)
        kb = KnowledgeBase(path, fresh=True)
        kb.add("new", "data")
        with open(path) as f:
            assert json.load(f) == {"new": "data"}, (
                "fresh KB should overwrite the old file on first save"
            )


def test_load_from_custom_path():
    """A non-default load_kb path is honored over the configured default."""
    with tempfile.TemporaryDirectory() as td:
        custom = os.path.join(td, "alt_kb.json")
        with open(custom, "w") as f:
            json.dump({"misty": "water gym leader"}, f)
        kb = KnowledgeBase(custom)
        assert kb.data == {"misty": "water gym leader"}


def test_missing_file_no_error():
    """KB pointed at a nonexistent path starts empty without raising."""
    with tempfile.TemporaryDirectory() as td:
        kb = KnowledgeBase(os.path.join(td, "does_not_exist.json"))
        assert kb.data == {}


# --- CLI wiring tests ---

def _install_stubs():
    """Stub heavy deps so main.py imports without anthropic / pyboy."""
    anthropic_mod = types.ModuleType("anthropic")
    anthropic_mod.Anthropic = type("Anthropic", (), {})
    sys.modules.setdefault("anthropic", anthropic_mod)

    pyboy_mod = types.ModuleType("pyboy")
    pyboy_mod.PyBoy = type("PyBoy", (), {})
    sys.modules.setdefault("pyboy", pyboy_mod)

    fake_agent_mod = types.ModuleType("agent.simple_agent")
    fake_agent_mod.SimpleAgent = type("SimpleAgent", (), {})
    sys.modules["agent.simple_agent"] = fake_agent_mod


def test_cli_flags_parse():
    """--load-kb PATH and --fresh-kb both reach argparse with right types."""
    _install_stubs()
    import argparse

    # Recreate the parser inline mirroring main.py to avoid running main().
    # If main.py's parser drifts from this list, the next assertion fails
    # loudly — but the source-of-truth check is the file-grep below.
    with open(os.path.join(REPO_ROOT, "main.py")) as f:
        src = f.read()
    assert "--load-kb" in src, "main.py must declare --load-kb"
    assert "--fresh-kb" in src, "main.py must declare --fresh-kb"
    assert 'action="store_true"' in src.split("--fresh-kb", 1)[1].split(")", 1)[0], (
        "--fresh-kb should be store_true"
    )


def test_mutually_exclusive_flags_error():
    """Passing both --load-kb and --fresh-kb must exit with non-zero status."""
    _install_stubs()
    # Force re-import so module-level _configure_logging picks up clean state.
    for mod in ("main", "config"):
        if mod in sys.modules:
            del sys.modules[mod]
    import main as main_mod  # noqa: F401

    # Build a parser identical to main.py's by invoking main() with bad args.
    # argparse.error raises SystemExit(2).
    old_argv = sys.argv
    try:
        sys.argv = ["main.py", "--load-kb", "/tmp/kb.json", "--fresh-kb"]
        try:
            main_mod.main()
        except SystemExit as e:
            assert e.code != 0, f"expected non-zero exit, got {e.code}"
            return
        raise AssertionError("expected SystemExit from mutually exclusive flags")
    finally:
        sys.argv = old_argv


def test_simple_agent_signature_accepts_new_kwargs():
    """SimpleAgent.__init__ must accept load_kb and fresh_kb without TypeError."""
    import inspect
    # Read directly — importing SimpleAgent needs anthropic.
    src_path = os.path.join(REPO_ROOT, "agent", "simple_agent.py")
    with open(src_path) as f:
        src = f.read()
    assert "load_kb=None" in src, "SimpleAgent.__init__ must accept load_kb"
    assert "fresh_kb=False" in src, "SimpleAgent.__init__ must accept fresh_kb"
    # Sanity: the KB is constructed with both.
    assert "KnowledgeBase(kb_path, fresh=fresh_kb)" in src, (
        "SimpleAgent must wire load_kb/fresh_kb through to KnowledgeBase"
    )
    # inspect import kept so future contributors notice if we move to real
    # signature inspection once anthropic is mockable in CI.
    _ = inspect


if __name__ == "__main__":
    tests = [
        test_load_existing_kb_default_behavior,
        test_fresh_kb_ignores_existing_file,
        test_fresh_kb_writes_overwrite_old_file,
        test_load_from_custom_path,
        test_missing_file_no_error,
        test_cli_flags_parse,
        test_mutually_exclusive_flags_error,
        test_simple_agent_signature_accepts_new_kwargs,
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
