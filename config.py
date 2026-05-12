# Configuration for the application.
#
# Models use Anthropic's stable aliases (e.g. "claude-sonnet-4-5"). Aliases
# remain valid for the model's full support window, which makes them the right
# choice for ship-and-forget deployments. If you need byte-for-byte
# determinism across runs (e.g. for benchmarking), swap to the dated snapshot
# string for the same model — see the README "Model selection" section.
#
# To verify a model name resolves before a long run (free; no token spend):
#     ANTHROPIC_API_KEY=$KEY python -c "from anthropic import Anthropic; \
#         print(Anthropic().models.retrieve('claude-sonnet-4-5').id)"
# A 404 means the alias is wrong — try a dated snapshot from
# https://docs.claude.com/en/docs/about-claude/models

# Main agent model. Sonnet 4.5 is the default — strong tool-use behavior,
# supports extended thinking, costs roughly 1/5 of Opus per token. For the
# full Twitch-stream experience, swap to "claude-opus-4-5" or current Opus.
MODEL_NAME = "claude-sonnet-4-5"
TEMPERATURE = 1.0           # Required to be 1.0 when THINKING_ENABLED.
MAX_TOKENS = 4000

USE_NAVIGATOR = False

SAVE_STATE_INTERVAL = 50   # Save every N agent steps
SAVE_STATE_DIR = "saves"

THOUGHTS_LOG_PATH = "thoughts.log"
THOUGHTS_HTML_PORT = 7861
# Truncate thoughts.log on agent startup. The OBS panel shows a rolling stream
# of recent reasoning, so keeping prior sessions across runs is rarely useful
# and the file would otherwise grow unbounded over multi-day streams.
THOUGHTS_LOG_TRUNCATE_ON_START = True

# Extended thinking ("Reasoning" panel on the public stream). Budget must be
# strictly less than MAX_TOKENS. Thinking output counts toward MAX_TOKENS.
THINKING_ENABLED = True
THINKING_BUDGET_TOKENS = 2000

KNOWLEDGE_BASE_PATH = "knowledge_base.json"

# Run log rotation. Stdout always gets the run log; this controls the optional
# file sink that survives the terminal closing. Path is mkdir-p'd at startup,
# and `logs/` is in .gitignore so the file is not committed by accident.
LOG_TO_FILE_ENABLED = True
LOG_FILE_PATH = "logs/agent.log"
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024   # 10 MB per file
LOG_FILE_BACKUP_COUNT = 5               # keep N rotated backups

# Critic LLM that reviews the knowledge base after each summarization event.
# Uses a smaller/cheaper model for cost and perspective diversity. The critic
# is wrapped in a try/except — if the model name is invalid, the failure is
# logged and the main loop continues without feedback. Verify the model with
# the snippet at the top of this file before a long run.
CRITIC_ENABLED = True
CRITIC_MODEL = "claude-haiku-4-5"
CRITIC_MAX_TOKENS = 500
# Critic gating semantics:
#   0 = never run (equivalent to CRITIC_ENABLED=False)
#   1 = every summarization (default)
#   N = every Nth summarization
# Negative values are rejected at import time. Useful for capping cost on
# multi-day streams where summarization fires roughly every 30 turns.
CRITIC_INTERVAL = 1

# Walkability image overlay. Doubles per-turn image bandwidth (a second
# 320x288 PNG alongside the plain screenshot). Set to False if running long
# sessions where token cost matters more than navigator-style grounding.
OVERLAY_ENABLED = True

# Walkability overlay colors (RGBA tuples). Tweak for color-blind palettes
# or stream branding. Alpha controls translucency — fills are intentionally
# semi-transparent so the underlying screenshot remains legible. Defaults
# preserve the original behavior; outlines are fully opaque.
OVERLAY_COLOR_WALL_FILL = (220, 30, 30, 110)     # translucent red — blocked tile
OVERLAY_COLOR_WALK_FILL = (40, 200, 80, 70)      # translucent green — walkable tile
OVERLAY_COLOR_SPRITE_OUTLINE = (255, 200, 0, 255)  # opaque yellow — NPC / sprite
OVERLAY_COLOR_PLAYER_OUTLINE = (80, 160, 255, 255) # opaque blue — player tile
OVERLAY_COLOR_PLAYER_ARROW = (80, 160, 255, 255)   # opaque blue — facing arrow

for _name, _val in (
    ("OVERLAY_COLOR_WALL_FILL", OVERLAY_COLOR_WALL_FILL),
    ("OVERLAY_COLOR_WALK_FILL", OVERLAY_COLOR_WALK_FILL),
    ("OVERLAY_COLOR_SPRITE_OUTLINE", OVERLAY_COLOR_SPRITE_OUTLINE),
    ("OVERLAY_COLOR_PLAYER_OUTLINE", OVERLAY_COLOR_PLAYER_OUTLINE),
    ("OVERLAY_COLOR_PLAYER_ARROW", OVERLAY_COLOR_PLAYER_ARROW),
):
    assert (
        isinstance(_val, tuple)
        and len(_val) == 4
        and all(isinstance(_c, int) and 0 <= _c <= 255 for _c in _val)
    ), f"{_name} must be a 4-tuple of ints in [0, 255], got {_val!r}"
del _name, _val

# Emulator heartbeat / auto-restart. Detects a frozen PyBoy by hashing the
# screenshot each step and comparing against a sliding window. If the last
# EMULATOR_HEARTBEAT_WINDOW screenshots are byte-identical AND the model
# emitted at least one button press during those steps, the agent logs a
# WARNING and re-initializes the emulator (reloading the most recent save
# state if one exists). Intentional no-input steps (e.g. waiting on a
# scrolling text box where the model called a non-emulator tool) do NOT
# count as hangs and do NOT trigger a reset.
EMULATOR_HEARTBEAT_ENABLED = True
EMULATOR_HEARTBEAT_WINDOW = 5

assert isinstance(EMULATOR_HEARTBEAT_WINDOW, int) and EMULATOR_HEARTBEAT_WINDOW >= 2, (
    "EMULATOR_HEARTBEAT_WINDOW must be an int >= 2 "
    "(a single sample cannot indicate a hang)"
)


# Fail-fast invariants — catch obvious misconfiguration at import time
# instead of letting it explode mid-run.
assert not THINKING_ENABLED or TEMPERATURE == 1.0, (
    "Anthropic requires TEMPERATURE == 1.0 when THINKING_ENABLED is True"
)
assert isinstance(CRITIC_INTERVAL, int) and CRITIC_INTERVAL >= 0, (
    "CRITIC_INTERVAL must be a non-negative int "
    "(0 = never, 1 = every summary, N = every Nth)"
)


# Model pricing in USD per million tokens, used by the startup cost estimate.
# Source: https://www.anthropic.com/pricing  (last verified 2026-05-08)
# Update when Anthropic posts new list prices — the startup [Cost] log will
# silently mislead operators otherwise.
#
# Keys are matched against MODEL_NAME and CRITIC_MODEL via prefix (so dated
# snapshots like "claude-sonnet-4-5-20250929" map to "claude-sonnet-4-5").
# Values are (input, output) per million tokens. Cache-hit pricing is not
# modeled here; expect realized cost to be 30-60% lower with a stable system
# prompt due to prompt caching.
MODEL_PRICING_PER_MTOK = {
    "claude-haiku-4-5":  (1.0, 5.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-opus-4-5":   (15.0, 75.0),
    # Older snapshots — kept for users who pin to legacy models
    "claude-3-5-haiku":  (0.80, 4.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-7-sonnet": (3.0, 15.0),
}
