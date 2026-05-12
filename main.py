import argparse
import logging
import logging.handlers
import os
from pathlib import Path

from agent.simple_agent import SimpleAgent
from config import (
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    LOG_FILE_PATH,
    LOG_TO_FILE_ENABLED,
)


def _configure_logging():
    """Configure stdout + rotating file handlers on the root logger.

    Stdout stays at INFO so terminals are not spammed; the file handler
    captures DEBUG for post-hoc analysis of multi-hour streams. Creates the
    parent dir of LOG_FILE_PATH (default ``logs/``) if missing. A file-handler
    failure is logged to stdout and skipped — the run continues without a
    file sink rather than refusing to start.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    stream = logging.StreamHandler()
    stream.setLevel(logging.INFO)
    stream.setFormatter(fmt)
    root.addHandler(stream)

    if not LOG_TO_FILE_ENABLED:
        return

    try:
        log_path = Path(LOG_FILE_PATH)
        if log_path.parent and str(log_path.parent) not in ("", "."):
            log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_path),
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as e:
        # Stdout handler is already installed, so this surfaces to the operator.
        logging.getLogger(__name__).error(
            f"Failed to attach RotatingFileHandler at {LOG_FILE_PATH}: {e}. "
            "Continuing with stdout logging only."
        )


_configure_logging()
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Claude Plays Pokemon - Starter Version")
    parser.add_argument(
        "--rom",
        type=str,
        default="pokemon.gb",
        help="Path to the Pokemon ROM file"
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=10,
        help="Number of agent steps to run"
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Run with display (not headless)"
    )
    parser.add_argument(
        "--sound",
        action="store_true",
        help="Enable sound (only applicable with display)"
    )
    parser.add_argument(
        "--max-history",
        type=int,
        default=30,
        help="Maximum number of messages in history before summarization"
    )
    parser.add_argument(
        "--load-state",
        type=str,
        default=None,
        help="Path to a saved state to load"
    )
    parser.add_argument(
        "--load-kb",
        type=str,
        default=None,
        help=(
            "Path to a knowledge_base.json to load. Independent of --load-state, "
            "so you can pair a fresh save state with a curated KB or vice versa. "
            "Defaults to the path in config.py."
        ),
    )
    parser.add_argument(
        "--fresh-kb",
        action="store_true",
        help=(
            "Start with an empty knowledge base regardless of whether a file "
            "exists at the configured path. Mutually exclusive with --load-kb."
        ),
    )

    args = parser.parse_args()

    if args.fresh_kb and args.load_kb:
        parser.error("--fresh-kb and --load-kb are mutually exclusive")

    # Get absolute path to ROM
    if not os.path.isabs(args.rom):
        rom_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.rom)
    else:
        rom_path = args.rom

    # Check if ROM exists
    if not os.path.exists(rom_path):
        logger.error(f"ROM file not found: {rom_path}")
        print("\nYou need to provide a Pokemon Red ROM file to run this program.")
        print("Place the ROM in the root directory or specify its path with --rom.")
        return

    # Create and run agent
    agent = SimpleAgent(
        rom_path=rom_path,
        headless=not args.display,
        sound=args.sound if args.display else False,
        max_history=args.max_history,
        load_state=args.load_state,
        load_kb=args.load_kb,
        fresh_kb=args.fresh_kb,
    )

    try:
        logger.info(f"Starting agent for {args.steps} steps")
        steps_completed = agent.run(num_steps=args.steps)
        logger.info(f"Agent completed {steps_completed} steps")
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, stopping")
    except Exception as e:
        logger.error(f"Error running agent: {e}")
    finally:
        agent.stop()

if __name__ == "__main__":
    main()
