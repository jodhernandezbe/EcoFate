# EcoFate entry points. Each target only wraps commands documented in the README.
# `make help` lists them.

SOURCES := agent app api commons config evals models prompts tools
PYTHON_FILES = $(shell git ls-files $(foreach dir,$(SOURCES),'$(dir)/*.py'))
WARM := from huggingface_hub import snapshot_download; \
	from config.read_across import get_read_across_settings as settings; \
	model = settings().model; snapshot_download(model.name, revision=model.revision)

.DEFAULT_GOAL := help
.PHONY: help up down build logs shell warm test lint check eval catalogue migrate

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

up: ## Build if needed and start the stack (http://127.0.0.1:8000)
	docker compose up --build --detach --wait

down: ## Stop the stack (volumes are kept)
	docker compose down

build: ## Build the images
	docker compose build

logs: ## Follow the stack's logs
	docker compose logs --follow

shell: ## Open a shell in the running api container
	docker compose exec api bash

warm: ## Download the pinned read-across encoder (~500 MB) into the model volume
	docker compose run --rm --no-deps api python -c "$(WARM)"

test: ## Run the unit tests (host, through uv)
	uv run pytest

lint: ## Format check and lint (ruff)
	uv run ruff format --check .
	uv run ruff check .

check: lint ## Everything pre-commit enforces: lint, types, security, function length, tests, frontend
	uv run pyright
	uv run bandit -c pyproject.toml -r $(SOURCES)
	uv run python scripts/check_function_length.py --max 18 $(PYTHON_FILES)
	uv run pytest
	npm --prefix frontend run check

eval: ## Agent evaluations on recorded tool outputs (OpenAI key, costs tokens)
	uv run pytest -m eval

catalogue: ## Every catalogue question through the live agent (OpenAI key, costs tokens)
	uv run python -m evals catalogue

migrate: ## Apply database migrations (nothing to migrate until PostgreSQL arrives)
	@echo "No database yet: nothing to migrate (added by migrate-to-postgresql)."
