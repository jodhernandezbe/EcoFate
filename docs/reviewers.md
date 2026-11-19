[← Documentation index](../README.md#documentation) · [All docs](README.md)

# For reviewers

Where to find each capstone criterion, in the rubric's order. To see the app without running it:
[Demo](demo.md).

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

## Self-evaluation

Scored against the course rubric (18 points, plus up to 17 bonus).

| Criterion | Max | Claimed | Evidence |
|---|---|---|---|
| Problem description | 2 | 2 | [The problem](../README.md#the-problem) and [What it does](../README.md#what-it-does) |
| Knowledge base and retrieval | 2 | 1 | A knowledge base is used: the SCC process index (Chroma) and the read-across encoder ([tools/](../tools/README.md)). Retrieval quality is not evaluated separately, so the second point is not claimed |
| Agents and LLM | 3 | 3 | One LangGraph agent with 12 documented tools ([agent/](../agent/README.md), [tools/](../tools/README.md#summary)) |
| Code organization | 2 | 2 | A layered Python project with enforced dependency rules ([Architecture](architecture.md#package-layers), `tests/test_layering.py`) |
| Testing | 2 | 2 | Unit tests and LLM-judge tests, with the commands for each ([Development](../DEVELOPMENT.md#tests), [evals/](../evals/docs/running-and-cost.md)) |
| Evaluation | 3 | 3 | An LLM judge scored against a labelled set of 50 answers and tuned over six prompt iterations, from 0.68 to 0.78 accuracy ([judge tuning](../evals/docs/judge-tuning.md)); the scripted scenarios guard prompt and tool-description changes ([scenarios](../evals/docs/scenarios.md)) |
| Monitoring | 2 | 2 | Logfire traces of every turn, model call and tool call, shown in the admin Monitoring view ([Monitoring](monitoring.md)) |
| Reproducibility | 2 | 2 | [Getting started](getting-started.md); the data is in the repository under `data/` |
| **Core total** | **18** | **17** | |

| Bonus | Max | Claimed | Evidence |
|---|---|---|---|
| Hand-crafted ground truth dataset | 2 | 2 | The 50 catalogue questions are hand-written (`evals/catalogue/scenarios.csv`, [catalogue and labels](../evals/docs/catalogue-and-labels.md)) |
| Manual evaluation against the ground truth | 2 | 0 | Not claimed: the labels come from a five-voter majority whose provenance is not recorded |
| User feedback collected | 1 | 0 | Not built |
| Logs turned into a ground truth dataset | 2 | 0 | Not built |
| Containerization | 1 | 1 | `Dockerfile`, `compose.yaml` |
| `docker compose up` starts the whole system | 2 | 2 | [Run with Docker](getting-started.md#run-with-docker) |
| Makefile | 1 | 1 | `Makefile` (`make help`) |
| Dependency management | 1 | 1 | uv (`pyproject.toml`, `uv.lock`) |
| CI/CD | 2 | 2 | Tests on every pull request and tag-driven deployment with rollback ([Development](../DEVELOPMENT.md#continuous-integration), [deploy/](../deploy/README.md)) |
| UI for the agent | 1 | 1 | The web workspace ([frontend/](../frontend/README.md)) and the command line |
| Deployed to the cloud | 2 | 2 | https://ecofate.org ([Deployment](deployment/README.md)) |
| **Bonus total** | **17** | **12** | |
