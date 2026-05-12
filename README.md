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

1. Clone and check out the working branch.  Create an explicit local tracking branch off the remote — this form works on any Git version, unlike a bare `git checkout ClaudeUpdates` which depends on the DWIM behavior added in Git 2.23+:
   ```bash
   git clone git@github.com:BriviantJosephD/ClaudePlaysPokemonStarterFork.git
   cd ClaudePlaysPokemonStarterFork
   git checkout -b ClaudeUpdates origin/ClaudeUpdates   # or `git switch ClaudeUpdates` on Git 2.23+
   git branch --show-current                            # should print ClaudeUpdates
   ```
   Once `ClaudeUpdates` is merged into `main` upstream, you can skip this step and stay on the default branch.

2. Install Python deps:
   ```bash
   pip install -r requirements.txt
   ```

3. Set your Anthropic API key:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

4. **Provide your own legally-owned Pokemon Red ROM** as `pokemon.gb` in the repo root.  You must own a physical Pokémon Red cartridge and dump the ROM yourself — this repository does not, and never will, distribute it.  Use `--rom PATH` if your file lives elsewhere.

5. (Recommended) verify your configured models resolve before a long run.  These calls hit `models.retrieve` — they are **free** and do not consume tokens.  Make sure `ANTHROPIC_API_KEY` is exported first:
   ```bash
   python -c "from anthropic import Anthropic; \
       print(Anthropic().models.retrieve('claude-sonnet-4-5').id)"
   python -c "from anthropic import Anthropic; \
       print(Anthropic().models.retrieve('claude-haiku-4-5').id)"
   ```
   Each command prints the resolved snapshot id (e.g. `claude-sonnet-4-5-20250929`).  A `NotFoundError` means the alias is wrong — pick a dated snapshot from [docs.claude.com/en/docs/about-claude/models](https://docs.claude.com/en/docs/about-claude/models) and edit `config.py`.

---

## Run a real session

The default `--steps 10` is for smoke-testing.  For an actual playthrough, run in **bounded sessions of a few hours** and resume from the latest save state.  Do NOT pass a multi-day budget — see the cost estimate below.

A typical session:

```bash
# ~3-8 hours of play depending on turn duration; ~$50-300 at default config
python main.py --steps 2000 --display
```

Resume from the latest checkpoint:

```bash
ls -1 saves/ | sort -V | tail -1
# autosave_step_2000_final.state
python main.py --load-state saves/autosave_step_2000_final.state --steps 2000
```

> ⚠️  **Estimate cost first.**  At default settings (Sonnet 4.5 + extended thinking + critic + overlay), a single 2,000-step session can run between $50 and $300 of API spend.  See [Estimated cost](#estimated-cost) below and set a billing alert in your Anthropic console before launching.

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

Start the static server **from the repo root** — the relative `fetch('thoughts.log')` in `thoughts.html` only resolves correctly when the server's working directory is the repo root:

```bash
cd /path/to/ClaudePlaysPokemonStarterFork
python -m http.server 7861
```

Add an OBS Browser Source pointing to:

```
http://localhost:7861/thoughts.html
```

> If the panel stays on "Waiting for thoughts...", open `http://localhost:7861/thoughts.log` directly in a browser.  It must return the file contents — a 404 means the server is running from the wrong directory.

The panel polls `thoughts.log` once per second, dark theme, monospace, autoscroll.  Port is configurable via `THOUGHTS_HTML_PORT` in `config.py` (port `7861` may conflict with Gradio's default — change to `7862` or another free port if needed).

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
| `OVERLAY_COLOR_*` | see `config.py` | RGBA tuples for walls / walkable / sprite / player / arrow. Retune for color-blind palettes or stream branding |
| `EMULATOR_HEARTBEAT_ENABLED` | `True` | Watchdog that resets PyBoy if N identical frames follow button presses (catches emulator hangs) |
| `EMULATOR_HEARTBEAT_WINDOW` | `5` | Number of consecutive identical frames required before a reset fires. Must be `>= 2` |
| `CRITIC_ENABLED` | `True` | One Haiku call per summarization (~every 30 turns); cheap but not free |
| `CRITIC_MODEL` | `claude-haiku-4-5` | Cheap reviewer model.  **Silent failure:** if the alias is invalid, the agent logs a warning and continues with no critic feedback — the run does not crash.  Verify before a long run. |
| `SAVE_STATE_INTERVAL` | `50` | Steps between auto-checkpoints |
| `USE_NAVIGATOR` | `False` | Enables the path-finding tool when in the overworld |

### Estimated cost

Per-turn token shape at default settings (Sonnet 4.5 + thinking + critic + overlay):

- **~7k input tokens** per turn — system prompt + rendered KB + screenshot + walkability overlay + RAM state + history
- **~2k thinking tokens** per turn — extended-thinking budget (`THINKING_BUDGET_TOKENS`), billed at the output rate
- **~1k output tokens** per turn — text reasoning + tool-use blocks

Throughput in practice is dominated by thinking + image encoding + emulator stepping: **~8-15 seconds per turn**, so **~250-450 turns per hour**.

Worked per-turn cost at Sonnet 4.5 list pricing ($3 / MTok input, $15 / MTok output):

```
(7,000 × $3 + 3,000 × $15) / 1,000,000  =  $0.021 + $0.045  =  $0.066 / turn
```

| Scenario | Per-hour estimate |
|---|---|
| Default config, no prompt caching | **~$16-30/hr** |
| Default config, with 50% input cache hit rate | **~$10-22/hr** |
| Default config, with 75% input cache hit rate (typical for stable system prompt) | **~$8-18/hr** |
| `OVERLAY_ENABLED=False` + `THINKING_ENABLED=False`, with caching | **~$1-3/hr** but materially weaker agent |

The agent prints a matching `[Cost]` line at startup so you can see the live estimate for your configured model.  A small additional Haiku cost is added for the critic (~$0.002 per summarization, ~once every 30 turns).

**A 2,000-step session ≈ 5-8 hours ≈ $50-200 at default config**, depending on caching.  If you swap `MODEL_NAME` to Opus, multiply by ~5×.  Always confirm against [Anthropic's current pricing](https://www.anthropic.com/pricing) and **set a billing alert in the Anthropic console before launching**.

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
| `test_memory_reader.py` | Unit tests for the safe-enum RAM-decoding fallback |
| `test_heartbeat.py` | Unit tests for the emulator hang-detection watchdog |

---

## Tests

```bash
make test
```

Three suites:
- `test_reminders.py` — 15 cases for low HP, fainted Pokemon, dialog `None` sentinel, narrow passage detection, navigation-failure nudges, malformed input.
- `test_memory_reader.py` — 11 cases for the safe-enum fallback path that keeps the agent running when RAM holds bytes outside the known enum range.
- `test_heartbeat.py` — 10 cases for the emulator watchdog: window discipline, button-press gating, reset-path coverage, hash-failure resilience.

---

## Model selection

This repo defaults to Anthropic aliases (`claude-sonnet-4-5`, `claude-haiku-4-5`).  Aliases stay valid for the model's full support window — the right choice for ship-and-forget.  If you need byte-for-byte determinism (e.g. for benchmarking), swap to a dated snapshot in `config.py`.  The following snapshots are listed in Anthropic's official model docs as of the README's verified date and are known-good fallbacks if the aliases ever fail to resolve:

```python
MODEL_NAME = "claude-sonnet-4-5-20250929"   # Sonnet 4.5, verified 2026-05-08
CRITIC_MODEL = "claude-haiku-4-5-20251001"  # Haiku 4.5,  verified 2026-05-08
```

If those snapshots have since been retired, run `make verify-models` (or the `models.retrieve` snippet in [Setup step 5](#setup)) to get the current alias resolution, then paste the printed id into `config.py`.  You can also paste a pinned dated string into the same snippet to confirm it still resolves against your API key before relying on it for a long run.  Anthropic typically deprecates dated snapshots ~12 months after release, so re-verify if the snapshot date above is more than a year stale.  Always pull current values from [docs.claude.com/en/docs/about-claude/models](https://docs.claude.com/en/docs/about-claude/models).

---

## Acknowledgements

Upstream by [@davidhershey](https://github.com/davidhershey).  Architecture diagram by Anthropic's CPP stream team.
