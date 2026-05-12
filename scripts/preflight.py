#!/usr/bin/env python3
"""Pre-run sanity checks for ClaudePlaysPokemonStarter.

Verifies the environment is wired correctly BEFORE you spend money on a
long run. Each check prints exactly one line:

    PASS: <what>
    FAIL: <what> - <next step>

Exits 0 if every check passes, non-zero otherwise. Run before any session:

    python scripts/preflight.py
    # or
    make preflight
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

# Locate the repo root so this script runs from any cwd. Inserting it on
# sys.path lets us import config.py without requiring a package install.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _print(ok: bool, what: str, next_step: str = "") -> None:
    if ok:
        print(f"PASS: {what}")
    else:
        print(f"FAIL: {what} - {next_step}")


def _check_rom(rom_path: Path) -> bool:
    if rom_path.is_file():
        _print(True, f"ROM present at {rom_path}")
        return True
    _print(
        False,
        f"ROM not found at {rom_path}",
        "place a legally-dumped Pokemon Red ROM at that path or pass --rom",
    )
    return False


def _check_api_key() -> bool:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key.strip():
        _print(True, "ANTHROPIC_API_KEY set")
        return True
    _print(
        False,
        "ANTHROPIC_API_KEY missing or empty",
        "export ANTHROPIC_API_KEY=sk-ant-... in your shell",
    )
    return False


def _check_model(client, label: str, model_id: str) -> bool:
    try:
        resolved = client.models.retrieve(model_id).id
    except Exception as e:  # noqa: BLE001 — surface whatever the SDK throws
        _print(
            False,
            f"{label} {model_id!r} did not resolve ({type(e).__name__})",
            "verify the alias at docs.claude.com/en/docs/about-claude/models and update config.py",
        )
        return False
    _print(True, f"{label} {model_id!r} resolves to {resolved}")
    return True


def _check_writable_dir(path: Path, label: str) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _print(False, f"{label} {path} not creatable ({e})", "fix directory permissions")
        return False
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".preflight_", delete=True):
            pass
    except OSError as e:
        _print(False, f"{label} {path} not writable ({e})", "fix directory permissions")
        return False
    _print(True, f"{label} {path} writable")
    return True


def _check_writable_parent(file_path: Path, label: str) -> bool:
    parent = file_path.parent if file_path.parent != Path("") else Path(".")
    parent = parent.resolve()
    return _check_writable_dir(parent, label)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-run sanity checks.")
    parser.add_argument(
        "--rom",
        default="pokemon.gb",
        help="ROM path to check (default: pokemon.gb at repo root, matching main.py)",
    )
    args = parser.parse_args()

    try:
        import config  # noqa: WPS433 — local import, repo root on sys.path
    except Exception as e:  # noqa: BLE001
        _print(False, "config.py import", f"resolve import error: {type(e).__name__}: {e}")
        return 1

    # Resolve paths relative to the repo root so the script works from any cwd.
    rom_path = Path(args.rom)
    if not rom_path.is_absolute():
        rom_path = (REPO_ROOT / rom_path).resolve()

    saves_dir = Path(getattr(config, "SAVE_STATE_DIR", "saves"))
    if not saves_dir.is_absolute():
        saves_dir = (REPO_ROOT / saves_dir).resolve()

    kb_path = Path(getattr(config, "KNOWLEDGE_BASE_PATH", "knowledge_base.json"))
    if not kb_path.is_absolute():
        kb_path = (REPO_ROOT / kb_path).resolve()

    logs_dir = REPO_ROOT / "logs"

    results: list[bool] = []
    results.append(_check_rom(rom_path))
    api_ok = _check_api_key()
    results.append(api_ok)

    # Model resolution requires the API key. Skip with FAIL if missing so the
    # operator sees exactly what's blocked and why.
    if api_ok:
        try:
            from anthropic import Anthropic
            client = Anthropic()
        except Exception as e:  # noqa: BLE001
            _print(False, "Anthropic client init", f"{type(e).__name__}: {e}")
            results.append(False)
            client = None
        if client is not None:
            results.append(_check_model(client, "MODEL_NAME", config.MODEL_NAME))
            results.append(_check_model(client, "CRITIC_MODEL", config.CRITIC_MODEL))
    else:
        _print(False, "MODEL_NAME resolution skipped", "set ANTHROPIC_API_KEY then re-run")
        _print(False, "CRITIC_MODEL resolution skipped", "set ANTHROPIC_API_KEY then re-run")
        results.append(False)
        results.append(False)

    results.append(_check_writable_dir(saves_dir, "saves/"))
    results.append(_check_writable_parent(kb_path, "knowledge_base.json parent"))
    results.append(_check_writable_dir(logs_dir, "logs/"))

    failed = results.count(False)
    if failed:
        print(f"\n{failed} check(s) failed.", file=sys.stderr)
        return 1
    print("\nAll preflight checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
