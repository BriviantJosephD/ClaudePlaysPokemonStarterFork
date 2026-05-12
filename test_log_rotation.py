"""Unit tests for the rotating-file run-log setup in main.py.

Run with: python3 test_log_rotation.py

main.py imports SimpleAgent transitively, which pulls in the Anthropic SDK
and PyBoy. To keep these tests stdlib-only, we stub the heavy modules in
sys.modules BEFORE importing main, then exercise its _configure_logging
helper against a temp directory.
"""

import logging
import logging.handlers
import os
import sys
import tempfile
import types

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)


def _install_stubs():
    """Insert minimal stand-in modules so `import main` does not pull deps."""
    # Stub `anthropic.Anthropic` — agent.critic and agent.simple_agent both
    # `from anthropic import Anthropic`. A bare class is enough; nothing
    # constructs it during import.
    anthropic_mod = types.ModuleType("anthropic")
    anthropic_mod.Anthropic = type("Anthropic", (), {})
    sys.modules.setdefault("anthropic", anthropic_mod)

    # Stub `pyboy` — only imported lazily inside agent.emulator, but be safe.
    pyboy_mod = types.ModuleType("pyboy")
    pyboy_mod.PyBoy = type("PyBoy", (), {})
    sys.modules.setdefault("pyboy", pyboy_mod)

    # Stub `agent.simple_agent.SimpleAgent` so main.py imports cleanly without
    # dragging in the full agent stack.
    fake_agent_mod = types.ModuleType("agent.simple_agent")
    fake_agent_mod.SimpleAgent = type("SimpleAgent", (), {})
    sys.modules["agent.simple_agent"] = fake_agent_mod


def _reset_root_logger():
    """Drop all handlers from the root logger so each test starts clean."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass


def _import_main_fresh():
    """Re-import main after stubbing, returning the module."""
    _install_stubs()
    if "main" in sys.modules:
        del sys.modules["main"]
    # config is read at main-import time; force a reload so any monkey-patched
    # constants are picked up.
    if "config" in sys.modules:
        del sys.modules["config"]
    import main  # noqa: E402
    return main


def test_rotating_handler_attached_with_configured_values():
    _reset_root_logger()
    import config
    # Point the log at a tempdir to avoid touching the real logs/ dir.
    with tempfile.TemporaryDirectory() as td:
        log_path = os.path.join(td, "sub", "agent.log")
        config.LOG_FILE_PATH = log_path
        config.LOG_FILE_MAX_BYTES = 1234
        config.LOG_FILE_BACKUP_COUNT = 3
        config.LOG_TO_FILE_ENABLED = True

        _install_stubs()
        if "main" in sys.modules:
            del sys.modules["main"]
        import main  # noqa: F401  — _configure_logging fires on import

        root = logging.getLogger()
        rotating = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(rotating) == 1, (
            f"expected exactly one RotatingFileHandler, got {len(rotating)} "
            f"(all handlers: {root.handlers!r})"
        )
        h = rotating[0]
        assert os.path.abspath(h.baseFilename) == os.path.abspath(log_path), (
            f"baseFilename {h.baseFilename!r} != expected {log_path!r}"
        )
        assert h.maxBytes == 1234, f"maxBytes {h.maxBytes} != 1234"
        assert h.backupCount == 3, f"backupCount {h.backupCount} != 3"
        assert h.level == logging.DEBUG, f"handler level {h.level} != DEBUG"

        # The logs/ directory should have been auto-created.
        assert os.path.isdir(os.path.dirname(log_path)), (
            f"expected parent dir {os.path.dirname(log_path)!r} to exist"
        )


def test_stdout_handler_still_present():
    """File handler is ADDITIVE — stdout logging must not be replaced."""
    _reset_root_logger()
    import config
    with tempfile.TemporaryDirectory() as td:
        config.LOG_FILE_PATH = os.path.join(td, "agent.log")
        config.LOG_TO_FILE_ENABLED = True

        _install_stubs()
        if "main" in sys.modules:
            del sys.modules["main"]
        import main  # noqa: F401

        root = logging.getLogger()
        stream_handlers = [
            h for h in root.handlers
            if type(h) is logging.StreamHandler  # exact type — RotatingFileHandler subclasses StreamHandler
        ]
        assert len(stream_handlers) >= 1, (
            f"expected at least one StreamHandler, got handlers={root.handlers!r}"
        )


def test_disabled_flag_skips_file_handler():
    _reset_root_logger()
    import config
    with tempfile.TemporaryDirectory() as td:
        config.LOG_FILE_PATH = os.path.join(td, "agent.log")
        config.LOG_TO_FILE_ENABLED = False

        _install_stubs()
        if "main" in sys.modules:
            del sys.modules["main"]
        import main  # noqa: F401

        root = logging.getLogger()
        rotating = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert not rotating, (
            f"expected no RotatingFileHandler when disabled, got {rotating!r}"
        )
        # And the log file should not have been created.
        assert not os.path.exists(config.LOG_FILE_PATH), (
            f"log file {config.LOG_FILE_PATH} should not exist when disabled"
        )


if __name__ == "__main__":
    tests = [
        test_rotating_handler_attached_with_configured_values,
        test_stdout_handler_still_present,
        test_disabled_flag_skips_file_handler,
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
