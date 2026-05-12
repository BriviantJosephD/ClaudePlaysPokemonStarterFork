.PHONY: help install test emulator-smoke smoke run serve-overlay verify-models clean

# Default ROM path; override on the command line: `make emulator-smoke ROM=roms/pokemon_red.gb`
ROM ?= pokemon.gb

help:
	@echo "Targets:"
	@echo "  make install         pip install -r requirements.txt"
	@echo "  make test            run unit tests (reminders + memory_reader + heartbeat)"
	@echo "  make emulator-smoke  emulator + ROM smoke test, ZERO API spend (set ROM=path/to.gb)"
	@echo "  make smoke           5-step agent smoke run (requires ANTHROPIC_API_KEY + ROM)"
	@echo "  make run             bounded play session (--steps 2000 --display)"
	@echo "  make serve-overlay   start static HTTP server for thoughts.html"
	@echo "  make verify-models   resolve MODEL_NAME and CRITIC_MODEL via models.retrieve"
	@echo "  make clean           remove .pyc, __pycache__, .pytest_cache, *.tmp, *.bak"

install:
	pip install -r requirements.txt

test:
	python3 test_reminders.py
	python3 test_memory_reader.py
	python3 test_heartbeat.py

emulator-smoke:
	python3 scripts/emulator_smoke.py --rom $(ROM)

smoke:
	python3 main.py --steps 5 --rom $(ROM)

run:
	python3 main.py --steps 2000 --display

serve-overlay:
	./scripts/serve_overlay.sh

verify-models:
	@if [ -z "$$ANTHROPIC_API_KEY" ]; then \
		echo "ERROR: ANTHROPIC_API_KEY is not set. export it and re-run." >&2; \
		exit 1; \
	fi
	@python3 -c "from anthropic import Anthropic; c=Anthropic(); \
import config; \
print('MODEL_NAME  →', c.models.retrieve(config.MODEL_NAME).id); \
print('CRITIC_MODEL→', c.models.retrieve(config.CRITIC_MODEL).id)"

# NOTE: clean intentionally does NOT touch saves/, knowledge_base.json, or
# thoughts.log — those are session artifacts the user often wants to keep.
# Delete them by hand if you really want a fresh state.
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.tmp" -delete 2>/dev/null || true
	find . -type f -name "*.bak" -delete 2>/dev/null || true
