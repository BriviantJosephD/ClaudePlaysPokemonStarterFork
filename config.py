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

# Critic LLM that reviews the knowledge base after each summarization event.
# Uses a smaller/cheaper model for cost and perspective diversity. The critic
# is wrapped in a try/except — if the model name is invalid, the failure is
# logged and the main loop continues without feedback. Verify the model with
# the snippet at the top of this file before a long run.
CRITIC_ENABLED = True
CRITIC_MODEL = "claude-haiku-4-5"
CRITIC_MAX_TOKENS = 500
# Run the critic every Nth summarization. 1 = every summary (default),
# 2 = every other, etc. Useful for capping cost on multi-day streams where
# summarization fires roughly every 30 turns.
CRITIC_INTERVAL = 1

# Walkability image overlay. Doubles per-turn image bandwidth (a second
# 320x288 PNG alongside the plain screenshot). Set to False if running long
# sessions where token cost matters more than navigator-style grounding.
OVERLAY_ENABLED = True


# Fail-fast invariant: Anthropic requires temperature == 1.0 when extended
# thinking is enabled. Catching this at import time beats getting a 400 from
# the API five minutes into a long run.
assert not THINKING_ENABLED or TEMPERATURE == 1.0, (
    "Anthropic requires TEMPERATURE == 1.0 when THINKING_ENABLED is True"
)


# Model pricing in USD per million tokens, used by the startup cost estimate.
# Update from https://www.anthropic.com/pricing as needed. Keys are matched
# against MODEL_NAME and CRITIC_MODEL via prefix (so dated snapshots like
# "claude-sonnet-4-5-20250929" map to "claude-sonnet-4-5"). Values are
# (input, output) per million tokens. Cache-hit pricing is not modeled here;
# expect actual cost to be 30-60% lower with a stable system prompt.
MODEL_PRICING_PER_MTOK = {
    "claude-haiku-4-5":  (1.0, 5.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-opus-4-5":   (15.0, 75.0),
    # Older snapshots — kept for users who pin to legacy models
    "claude-3-5-haiku":  (0.80, 4.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-7-sonnet": (3.0, 15.0),
}
