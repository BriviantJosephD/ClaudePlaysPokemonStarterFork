# todo.md

Tracking what's left for `ClaudePlaysPokemonStarterFork` to be ship-and-forget — i.e. a stranger could clone, follow the README, and run a multi-hour Pokemon Red playthrough that streams to Twitch with no follow-up tinkering.

Architectural parity with the production Twitch diagram is **complete** (knowledge base, critic, extended thinking, save state, stream-of-thought, walkability overlay, helpful reminders, enriched system prompt).  What remains is operational hygiene.

---

## Tier 1 — Must-have to run a real session

- [x] **Verify `CRITIC_MODEL` and document silent-failure behavior.**  Replaced billable `messages.create` probe with free `client.models.retrieve()` snippet in both `config.py` and README.  Documented silent-failure in the README config-knob row.

- [x] **Update `MODEL_NAME` to a current Sonnet.**  Bumped from `claude-3-7-sonnet-20250219` to the alias `claude-sonnet-4-5`.  Documented alias-vs-snapshot tradeoff.  Added an import-time `assert` enforcing `TEMPERATURE == 1.0` when `THINKING_ENABLED`.

- [x] **`.gitignore` for runtime artifacts.**  Added `knowledge_base.json`, `saves/`, `thoughts.log`, `*.tmp`, `*.bak`, `.claude/worktrees/`, `.claude/settings.local.json`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`.  ROM (`*.gb`) and `.env` were already covered.

- [x] **`README.md`.**  Full rewrite landed.  Setup, real-session pattern (bounded `--steps 2000` + resume from latest save), OBS overlay setup with explicit cwd, every config knob with cost notes, defensible cost estimate with worked math (currently ~$16-30/hr at default config, no caching), file map, tests, model-selection guidance with `YYYYMMDD` placeholder pattern, ROM legal/practical note.

---

## Tier 2 — Quality polish before "ship and forget" is truthful

- [x] **Test runner.**  `Makefile` with `install`/`test`/`smoke`/`run`/`serve-overlay`/`verify-models`/`clean` targets.  `make verify-models` resolves the configured aliases via the free `models.retrieve` endpoint and refuses to run without `ANTHROPIC_API_KEY`.

- [x] **Token-cost visibility at startup.**  New `MODEL_PRICING_PER_MTOK` table in `config.py` + `_log_cost_estimate()` method on `SimpleAgent` prints expected per-turn USD and per-hour ranges including the amortized critic contribution.  Pricing source URL and last-verified date documented inline.

- [x] **Roll `thoughts.log`.**  `THOUGHTS_LOG_TRUNCATE_ON_START` (default `True`).  `SimpleAgent.__init__` archives the prior log to `<path>.prev` rather than truncating in place — preserves the last session and is atomic on POSIX.  Mkdirs the parent directory so users can point the log at a subdirectory like `logs/thoughts.log`.

- [x] **OBS overlay helper.**  `scripts/serve_overlay.sh` `cd`s to repo root regardless of cwd, sources port from `config.py` with a stderr warning on fallback, prints the OBS Browser Source URL.

- [x] **Fainted-Pokemon reminder.**  HP rule in `agent/reminders.py` distinguishes fainted (HP == 0, switch/Revive) from low (0 < HP/max < 25%, PokeCenter); both can fire in the same turn.  Two new tests cover the dedicated reminder and combined firing.

- [x] **`CRITIC_INTERVAL` knob.**  New config constant (default `1`).  `SimpleAgent.summarize_history` gates the critic on `summary_count % CRITIC_INTERVAL == 0` and logs skips so the cadence is verifiable in long runs.  Import-time `assert` rejects negative values.

---

## Tier 3 — Reach goals (skip until something bites)

- [ ] **Emulator health check / auto-restart.**  If PyBoy hangs, the agent loops on a frozen screen with no recovery.  Add a per-step heartbeat that compares screenshot hashes; if N consecutive screenshots are byte-identical AND the model emitted button presses, log a warning and reset the emulator.

- [x] **Run log rotation to file.**  `main.py` now configures a `RotatingFileHandler` at `logs/agent.log` (DEBUG level) alongside the existing stdout handler.  Knobs: `LOG_FILE_PATH`, `LOG_FILE_MAX_BYTES` (10 MB default), `LOG_FILE_BACKUP_COUNT` (5 default), `LOG_TO_FILE_ENABLED` (True default).  Parent dir auto-created; `logs/` was already in `.gitignore`.

- [ ] **Pre-run sanity script.**  `scripts/preflight.py` that checks: ROM exists, `ANTHROPIC_API_KEY` set, `MODEL_NAME` resolves (1-token call), `CRITIC_MODEL` resolves, write permission to `saves/` and `knowledge_base.json`.  Exits non-zero with a clear message if any check fails.  Save users from "agent silently does nothing for 5 minutes" debugging.

- [x] **Resume-from-knowledge-base UX.**  Added `--load-kb PATH` (independent of `--load-state`) and `--fresh-kb` (start empty regardless of file presence; mutually exclusive with `--load-kb`).  `KnowledgeBase.__init__` gained a `fresh` kwarg that skips the file load but leaves the on-disk file intact until the next write.  README documents the mix-and-match patterns.

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
- [x] Unit tests — `test_reminders.py` (15 cases) + `test_memory_reader.py` (11 cases) = 26/26 passing
- [x] **Tier 1 ship-and-forget readiness** — model alias bump, free model verification snippet, `.gitignore` for runtime artifacts, full README rewrite with bounded-session pattern, defensible cost math, OBS setup, ROM legality note, dated-snapshot placeholder pattern, `TEMPERATURE`/`THINKING` import-time assert
- [x] **Tier 2 quality polish** — Makefile (test/run/serve/verify/clean), startup `[Cost]` log with critic-amortized pricing, `thoughts.log` rotation via archive-to-`.prev`, `scripts/serve_overlay.sh`, fainted-Pokemon reminder, `CRITIC_INTERVAL` config knob
- [x] **Codex review pass** — first Claude turn now seeds a real observation (screenshot + overlay + RAM + reminders) so the model doesn't act blind; `agent/memory_reader.py` enum constructions hardened via `_safe_enum` + `_UnknownEnumMember` stand-in so unknown RAM bytes degrade gracefully instead of crashing the run; README setup uses explicit `git checkout -b ClaudeUpdates origin/ClaudeUpdates` (any-Git compatible); pinned codex-confirmed dated snapshots (`claude-sonnet-4-5-20250929`, `claude-haiku-4-5-20251001`) with ~12-month deprecation window
- [x] **Test-suite dedup** — `agent/memory_reader.py` gains `from __future__ import annotations` (PEP 563) so the pre-existing PEP 604 union syntax loads on Python 3.9+; `test_memory_reader.py` now imports the real `_safe_enum` / `_UnknownEnumMember` / `_safe_enum_reset` directly instead of carrying a shadow copy that could drift; added cross-checks against the real `PokemonType` and `Move` enums
