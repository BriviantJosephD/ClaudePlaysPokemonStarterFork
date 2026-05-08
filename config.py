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
