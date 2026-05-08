# todo.md

Tracking what's left for `ClaudePlaysPokemonStarterFork` to be ship-and-forget — i.e. a stranger could clone, follow the README, and run a multi-hour Pokemon Red playthrough that streams to Twitch with no follow-up tinkering.

Architectural parity with the production Twitch diagram is **complete** (knowledge base, critic, extended thinking, save state, stream-of-thought, walkability overlay, helpful reminders, enriched system prompt).  What remains is operational hygiene.

---

## Tier 1 — Must-have to run a real session

- [x] **Verify `CRITIC_MODEL` and document silent-failure behavior.**  Replaced billable `messages.create` probe with free `client.models.retrieve()` snippet in both `config.py` and README.  Documented silent-failure in the README config-knob row.

- [x] **Update `MODEL_NAME` to a current Sonnet.**  Bumped from `claude-3-7-sonnet-20250219` to the alias `claude-sonnet-4-5`.  Documented alias-vs-snapshot tradeoff.  Added an import-time `assert` enforcing `TEMPERATURE == 1.0` when `THINKING_ENABLED`.

- [x] **`.gitignore` for runtime artifacts.**  Added `knowledge_base.json`, `saves/`, `thoughts.log`, `*.tmp`, `*.bak`, `.claude/worktrees/`, `.claude/settings.local.json`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`.  ROM (`*.gb`) and `.env` were already covered.

- [x] **`README.md`.**  Full rewrite landed.  Setup, real-session pattern (bounded `--steps 2000` + resume from latest save), OBS overlay setup with explicit cwd, every config knob with cost notes, defensible cost estimate (~$25-120/hr at default config with worked math), file map, tests, model-selection guidance with `YYYYMMDD` placeholder pattern, ROM legal/practical note.

---

## Tier 2 — Quality polish before "ship and forget" is truthful

- [ ] **Add a test runner.**  Today: `python3 test_reminders.py` works but is manual.
  - Either add a `Makefile` with `make test`, or rename to `test_reminders.py` → `tests/test_reminders.py` and document `pytest` invocation.
  - CI is out of scope for now but a one-liner test command is in scope.

- [ ] **Token-cost visibility at startup.**  Extend the `[Config]` log line in `agent/simple_agent.py` to include a rough per-turn token estimate (system prompt + screenshot + overlay + memory ≈ ~5-8k input, ~2-3k thinking, ~1k output).  Print expected $/hour at the configured rate so a long-run user knows what they're committing to.

- [ ] **Rotate `thoughts.log`.**  Currently grows unbounded.  Options (pick one):
  - Truncate on every `SimpleAgent.__init__` (simplest; loses prior session)
  - Cap at N MB and rotate to `thoughts.log.1` (more familiar)
  - Cap at last N entries via in-memory ring + periodic flush

- [ ] **Helper script for the OBS overlay.**  Add `scripts/serve_overlay.sh` (or a Makefile target) that runs `python -m http.server $THOUGHTS_HTML_PORT` from the repo root.  Reduces "what command was that again" friction.

- [ ] **Fainted-Pokemon reminder.**  Reviewer flagged this and we deferred.  Add a sixth rule in `agent/reminders.py` that fires when ANY party member has `HP: 0/X` — message: "A Pokemon has fainted.  Switch to a healthy Pokemon or use a Revive."

- [ ] **`CRITIC_INTERVAL` knob.**  Critic currently runs on every summarization (~every 30 turns).  For 24-hour streams that's 50-100 critic calls.  Add a config knob to run the critic every N summarizations instead of every one; default to 1 (current behavior).

---

## Tier 3 — Reach goals (skip until something bites)

- [ ] **Emulator health check / auto-restart.**  If PyBoy hangs, the agent loops on a frozen screen with no recovery.  Add a per-step heartbeat that compares screenshot hashes; if N consecutive screenshots are byte-identical AND the model emitted button presses, log a warning and reset the emulator.

- [ ] **Run log rotation to file.**  Today logs go only to stdout.  For multi-hour streams, configure `logging.handlers.RotatingFileHandler` writing to `logs/agent.log` so post-hoc analysis is feasible.

- [ ] **Pre-run sanity script.**  `scripts/preflight.py` that checks: ROM exists, `ANTHROPIC_API_KEY` set, `MODEL_NAME` resolves (1-token call), `CRITIC_MODEL` resolves, write permission to `saves/` and `knowledge_base.json`.  Exits non-zero with a clear message if any check fails.  Save users from "agent silently does nothing for 5 minutes" debugging.

- [ ] **Resume-from-knowledge-base UX.**  Currently the KB is the only durable signal across crashes.  Add an explicit "load this KB" CLI flag separate from `--load-state` so a user can play forward from a save state with a fresh KB or vice versa.

- [ ] **Walkability overlay color customization.**  Hard-coded RGBA values in `agent/emulator.py:get_collision_overlay_image`.  Move to `config.py` for accessibility (color-blind palette) or stream branding.

- [ ] **Smoke-test script that runs 5 agent steps with a real ROM.**  No assertions about gameplay quality — just verifies the loop doesn't crash, tools dispatch, screenshot + overlay + memory + reminders all populate.  Should be fast enough to run before every push.

---

## Done — kept here for reference

- [x] Knowledge base tool with persistent JSON storage (`agent/knowledge_base.py`)
- [x] Haiku-based critic at summarization time (`agent/critic.py`)
- [x] Extended thinking enabled with proper block preservation
- [x] Periodic save state every `SAVE_STATE_INTERVAL` steps + final save on `stop()`
- [x] Stream-of-thought log + OBS-ready HTML overlay (`thoughts.html`)
- [x] Walkability image overlay drawn on screenshots
- [x] Situational helpful reminders appended to use_emulator results (`agent/reminders.py`)
- [x] Enriched system prompt with tool tips and weakness reminders
- [x] Code review fixes (XML escaping, atomic writes, redacted_thinking, dialog "None" sentinel)
- [x] Unit tests for the reminders module (13/13 passing)
- [x] **Tier 1 ship-and-forget readiness** — model alias bump, free model verification snippet, `.gitignore` for runtime artifacts, full README rewrite with bounded-session pattern, defensible cost math, OBS setup, ROM legality note, dated-snapshot placeholder pattern, `TEMPERATURE`/`THINKING` import-time assert
