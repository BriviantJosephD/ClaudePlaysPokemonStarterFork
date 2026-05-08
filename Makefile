.PHONY: help install test smoke run serve-overlay verify-models clean

help:
	@echo "Targets:"
	@echo "  make install         pip install -r requirements.txt"
	@echo "  make test            run unit tests (test_reminders.py)"
	@echo "  make smoke           5-step headless smoke run (requires pokemon.gb)"
	@echo "  make run             bounded play session (--steps 2000 --display)"
	@echo "  make serve-overlay   start static HTTP server for thoughts.html"
	@echo "  make verify-models   resolve MODEL_NAME and CRITIC_MODEL via models.retrieve"
	@echo "  make clean           remove .pyc, __pycache__, .pytest_cache, *.tmp, *.bak"

install:
	pip install -r requirements.txt

test:
	python3 test_reminders.py

smoke:
	python3 main.py --steps 5

run:
	python3 main.py --steps 2000 --display

serve-overlay:
	./scripts/serve_overlay.sh

verify-models:
	@python3 -c "from anthropic import Anthropic; c=Anthropic(); \
import config; \
print('MODEL_NAME  →', c.models.retrieve(config.MODEL_NAME).id); \
print('CRITIC_MODEL→', c.models.retrieve(config.CRITIC_MODEL).id)"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.tmp" -delete 2>/dev/null || true
	find . -type f -name "*.bak" -delete 2>/dev/null || true
