# Claude Plays Pokemon — Fork

Fork of [`davidhershey/ClaudePlaysPokemonStarter`](https://github.com/davidhershey/ClaudePlaysPokemonStarter) extended to match the production architecture used by the public Twitch stream at [twitch.tv/claudeplayspokemon](https://twitch.tv/claudeplayspokemon).

The agent runs Pokemon Red on the PyBoy emulator and drives input through Claude.  It maintains a persistent knowledge base, summarizes long histories, ships extended-thinking output to a separate "Reasoning" panel, captures the running stream-of-thought to a file an OBS browser source can render, periodically checkpoints the emulator, and runs a cheap critic LLM to keep the knowledge base honest.

---

## What's in this fork beyond the starter

- **Knowledge base tool** (`agent/knowledge_base.py`) — durable JSON-backed notes the agent writes via the `update_knowledge_base` tool.  Rendered into the system prompt every turn.
- **Critic LLM** (`agent/critic.py`) — small Haiku model reviews the KB after each summarization and emits short suggestions.  Cheap; runs only on summary events.
- **Extended thinking** — enabled on every `messages.create` call.  Thinking blocks are preserved in assistant history per Anthropic's tool-use requirements.
- **Save state** (`agent/emulator.py`) — atomic checkpoints written every `SAVE_STATE_INTERVAL` steps and on clean exit.
- **Stream-of-thought** (`thoughts.html` + `thoughts.log`) — every text block the model emits is appended to a tailable log.  An OBS-friendly HTML page renders it live.
- **Walkability image overlay** — translucent grid drawn over the screenshot showing walls / walkable tiles / NPCs / player direction.
- **Helpful reminders** (`agent/reminders.py`) — situational nudges (low HP, dialog active, narrow passage, etc.) appended to each tool result.
- **Enriched system prompt** — explicit weakness reminders and tool-usage tips.

Open items tracked in [`todo.md`](todo.md).

---

## Setup

1. Clone:
   ```bash
   git clone git@github.com:BriviantJosephD/ClaudePlaysPokemonStarterFork.git
   cd ClaudePlaysPokemonStarterFork
   ```

2. Install Python deps:
   ```bash
   pip install -r requirements.txt
   ```

3. Set your Anthropic API key:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

4. **Provide your own legally-owned Pokemon Red ROM** as `pokemon.gb` in the repo root.  The ROM is not, and will never be, included in this repository.

5. (Optional but recommended) verify your configured models resolve before a long run:
   ```bash
   python -c "from anthropic import Anthropic; \
       print(Anthropic().messages.create(model='claude-sonnet-4-5', \
       max_tokens=10, messages=[{'role':'user','content':'hi'}]).model)"
   python -c "from anthropic import Anthropic; \
       print(Anthropic().messages.create(model='claude-haiku-4-5', \
       max_tokens=10, messages=[{'role':'user','content':'hi'}]).model)"
   ```
   A `404` means the alias is wrong — edit `config.py` and try a dated snapshot.

---

## Run a real session

The default `--steps 10` is for smoke-testing.  For an actual playthrough, give the agent enough budget to make progress:

```bash
python main.py --steps 100000 --display
```

Or run unattended with checkpointing:

```bash
python main.py --steps 100000 --max-history 30
```

Resume from a checkpoint:

```bash
python main.py --load-state saves/autosave_step_500.state --steps 100000
```

### CLI options

| Flag | Default | Description |
|---|---|---|
| `--rom` | `pokemon.gb` | Path to the ROM file |
| `--steps` | `10` | Agent step budget for this invocation |
| `--display` | off | Show the emulator window (vs headless) |
| `--sound` | off | Enable sound (requires `--display`) |
| `--max-history` | `30` | Turns before history is summarized |
| `--load-state` | none | Path to a saved state to resume from |

---

## Stream the reasoning panel (for OBS / Twitch)

The agent appends every `text` block (Claude's spoken reasoning) to `thoughts.log`.  A tiny static page renders the rolling log live in OBS browser source style.

Start the static server from the repo root:

```bash
python -m http.server 7861
```

Add an OBS Browser Source pointing to:

```
http://localhost:7861/thoughts.html
```

The panel polls `thoughts.log` once per second, dark theme, monospace, autoscroll.  Port is configurable via `THOUGHTS_HTML_PORT` in `config.py`.

---

## Configuration knobs (`config.py`)

| Knob | Default | What it costs |
|---|---|---|
| `MODEL_NAME` | `claude-sonnet-4-5` | Sonnet ≈ 1/5 the cost of Opus per token; Opus is the closest match to the Twitch stream |
| `TEMPERATURE` | `1.0` | **Required to be 1.0 when `THINKING_ENABLED`** — do not change |
| `MAX_TOKENS` | `4000` | Output budget per turn including thinking |
| `THINKING_ENABLED` | `True` | Adds the "Reasoning" panel; ~2× output tokens per turn |
| `THINKING_BUDGET_TOKENS` | `2000` | Max tokens spent on thinking; must be `< MAX_TOKENS` |
| `OVERLAY_ENABLED` | `True` | Doubles per-turn image bandwidth (second 320×288 PNG); turn off for cost-sensitive long runs |
| `CRITIC_ENABLED` | `True` | One Haiku call per summarization (~every 30 turns); cheap but not free |
| `CRITIC_MODEL` | `claude-haiku-4-5` | Cheap reviewer model |
| `SAVE_STATE_INTERVAL` | `50` | Steps between auto-checkpoints |
| `USE_NAVIGATOR` | `False` | Enables the path-finding tool when in the overworld |

### Estimated cost

Rough back-of-envelope at default settings (Sonnet 4.5 + thinking + critic + overlay) on Anthropic's standard pricing as of 2026:

- ~5-8k input tokens per turn (system prompt + KB + screenshot + overlay + memory)
- ~2-3k thinking tokens per turn
- ~1k output tokens per turn
- ~1 turn / 2 seconds → ~1,800 turns / hour

Expect **roughly $5-15 per hour of play** at default config.  Disable `OVERLAY_ENABLED` and `THINKING_ENABLED` to drop that significantly at the cost of agent quality.  Always confirm against [Anthropic's current pricing](https://www.anthropic.com/pricing) before a long run.

---

## How it works

```
┌────────────────────────────────────────────────────────────┐
│                     Core loop (per turn)                    │
│                                                             │
│   1. Compose prompt: system + KB.render() + history         │
│   2. Call Claude with tools, thinking enabled               │
│   3. Log text blocks → thoughts.log                         │
│   4. Preserve thinking blocks in assistant history          │
│   5. Dispatch tool calls:                                   │
│        - press_buttons / navigate_to                        │
│        - update_knowledge_base                              │
│   6. Build tool_result with screenshot + overlay +          │
│      RAM state + helpful reminders                          │
│   7. Append result to history                               │
│   8. If history > max_history → summarize_history()         │
│        - Claude writes a summary                            │
│        - Critic reviews the KB                              │
│        - History replaced with summary + critique           │
│   9. Every SAVE_STATE_INTERVAL steps → atomic save state    │
└────────────────────────────────────────────────────────────┘
```

### File map

| Path | Purpose |
|---|---|
| `main.py` | CLI entry point |
| `config.py` | All configuration knobs |
| `agent/simple_agent.py` | Main loop, history/summarization, tool dispatch |
| `agent/emulator.py` | PyBoy wrapper, screenshot, collision map, save/load state |
| `agent/memory_reader.py` | Reads RAM state (party, badges, dialog, inventory) |
| `agent/knowledge_base.py` | Persistent JSON-backed notes |
| `agent/critic.py` | Haiku-based KB reviewer |
| `agent/reminders.py` | Situational reminder rules |
| `thoughts.html` | OBS-friendly stream-of-thought overlay |
| `test_reminders.py` | Unit tests for the reminder rules |

---

## Tests

```bash
python3 test_reminders.py
```

13 cases covering low HP, fainted Pokemon, dialog `None` sentinel, narrow passage detection, navigation-failure nudges, malformed input.

---

## Model selection

This repo defaults to Anthropic aliases (`claude-sonnet-4-5`, `claude-haiku-4-5`).  Aliases stay valid for the model's full support window — the right choice for ship-and-forget.  If you need byte-for-byte determinism (e.g. for benchmarking), swap to a dated snapshot in `config.py`:

```python
MODEL_NAME = "claude-sonnet-4-5-20250929"   # example dated snapshot
CRITIC_MODEL = "claude-haiku-4-5-20251001"  # example dated snapshot
```

The exact snapshot strings change over time — check [`docs.anthropic.com/en/docs/about-claude/models`](https://docs.claude.com/en/docs/about-claude/models) for current values.

---

## Acknowledgements

Upstream by [@davidhershey](https://github.com/davidhershey).  Architecture diagram by Anthropic's CPP stream team.
