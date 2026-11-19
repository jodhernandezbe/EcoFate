[← Documentation index](../README.md#documentation) · [All docs](README.md)

# For reviewers

Where to find each capstone criterion, in the rubric's order.

| Criterion | Where it is | Check it |
|---|---|---|
| Problem description | [The problem](../README.md#the-problem), [What it does](../README.md#what-it-does) | This page |
| Knowledge base and retrieval | SCC process retrieval (Chroma) and read-across: [tools/](../tools/README.md) | `uv run pytest tests/tools` |
| Agent, LLM and tools | [agent/](../agent/README.md), [tools/](../tools/README.md), [prompts/](../prompts/README.md) | `uv run python -m app "Assess CAS 71-43-2"` |
| Code organization | [Architecture](architecture.md#package-layers) and the folder READMEs | `uv run pyright` |
| Testing | Unit, PostgreSQL, Redis, frontend and judge tests: [Development](../DEVELOPMENT.md) | `make check`, `make test-db`, `make test-redis` |
| Evaluation | Scenarios, hand-written catalogue, labels, LLM judge tuning: [evals/](../evals/README.md) | `make eval` (costs tokens) |
| Monitoring | Logfire traces and the admin view: [Monitoring](monitoring.md) | Monitoring in the rail (admin) |
| Reproducibility | [Run with Docker](getting-started.md#run-with-docker), [Local development](getting-started.md#local-development-with-uv); data under `data/` | `docker compose --profile dev up --build` |
| Best coding practices | Docker, compose, Makefile, uv, pre-commit gates, CI: [Development](../DEVELOPMENT.md) | `uv run pre-commit run --all-files` |
| Deployment | https://ecofate.org: [Deployment guide](deployment/README.md), [deploy/](../deploy/README.md) | `curl https://ecofate.org/api/health` |
