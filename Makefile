# EcoFate entry points. Each target only wraps commands documented in the README.
# `make help` lists them.

SOURCES := agent app api commons config evals models prompts storage tools worker
PYTHON_FILES = $(shell git ls-files $(foreach dir,$(SOURCES),'$(dir)/*.py'))
WARM := from huggingface_hub import snapshot_download; \
	from config.read_across import get_read_across_settings as settings; \
	model = settings().model; snapshot_download(model.name, revision=model.revision)

.DEFAULT_GOAL := help
.PHONY: help up down build logs worker-logs shell warm test lint check audit eval catalogue migrate db test-db redis test-redis psql

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

worker-logs: ## Follow the background worker's logs (the turns it runs)
	docker compose logs --follow worker

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

# Advisories accepted after review, each with its reason; anything else fails the audit. Revisit
# when chromadb ships a fix (remove the ID) or the reason stops holding.
# chromadb: all four concern the Chroma *server* (its HTTP API and RBAC provider); EcoFate uses
# only the embedded PersistentClient (tools/emissions/rag/vectorstore.py) and runs no server.
#   PYSEC-2026-311   pre-auth code injection via the collections HTTP endpoint (trust_remote_code)
#   PYSEC-2026-3814  authenticated code injection via the collection HTTP endpoint
#   PYSEC-2026-3813  cross-tenant data access for authenticated server users
#   PYSEC-2026-3815  SimpleRBACAuthorizationProvider ignores the permission's scope
AUDIT_ACCEPTED := PYSEC-2026-311 PYSEC-2026-3814 PYSEC-2026-3813 PYSEC-2026-3815

audit: ## Dependency vulnerability audit (pip-audit; reviewed exceptions listed above)
	uv run pip-audit --progress-spinner off $(foreach id,$(AUDIT_ACCEPTED),--ignore-vuln $(id))

eval: ## Agent evaluations on recorded tool outputs (OpenAI key, costs tokens)
	uv run pytest -m eval

catalogue: ## Every catalogue question through the live agent (OpenAI key, costs tokens)
	uv run python -m evals catalogue

migrate: ## Apply the database migrations (starts db if needed)
	docker compose run --rm --build migrate

db: ## Start only PostgreSQL, on 127.0.0.1:5432 (native runs and make test-db)
	docker compose --profile dev up --detach --wait db db-port

test-db: db ## Run the PostgreSQL tests (pytest -m postgres) against the db service
	@set -a && . ./.env && set +a && \
	ECOFATE_TEST_DATABASE_URL="$${ECOFATE_TEST_DATABASE_URL:-postgresql://$$POSTGRES_USER:$$POSTGRES_PASSWORD@127.0.0.1:5432/$$POSTGRES_DB}" \
	uv run pytest -m postgres

redis: ## Start only Redis, on 127.0.0.1:6379 (native runs and make test-redis)
	docker compose --profile dev up --detach --wait redis redis-port

test-redis: redis ## Run the Redis tests (pytest -m redis) against the redis service
	ECOFATE_TEST_REDIS_URL="$${ECOFATE_TEST_REDIS_URL:-redis://127.0.0.1:6379/15}" uv run pytest -m redis

psql: ## Open a psql shell in the db service
	docker compose exec db sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'
