[← Documentation index](../README.md#documentation) · [All docs](README.md)

# Getting started

- [Run with Docker](getting-started.md#run-with-docker)
- [Local development with uv](#local-development-with-uv)

## Run with Docker

Only Docker is needed (Docker Desktop on macOS or Windows).

    cp .env.example .env     # set POSTGRES_PASSWORD, ECOFATE_SESSION_SECRET, the key-encryption key,
                             # and the operator's CENSUS_API_KEY and COMPTOX_API_KEY
    docker compose --profile dev up --build   # first build takes several minutes
    # open http://127.0.0.1:8000, sign up, open the verification link at http://127.0.0.1:8025,
    # then save your own OpenAI key in Settings

The image is about 2 GB and the stack needs about 4 GB of RAM once the read-across encoder is
loaded. After changing code, recreate the containers: `docker compose up -d --build --force-recreate api worker tool-worker`.
What goes in `.env` and why: [api/](../api/docs/keys-and-byok.md) and [Security](security/README.md).
The services and their health check: [Architecture](architecture.md#runtime-containers).

The `Makefile` is the index of everyday commands (`make help` lists them):

| Target | What it does |
|--------|--------------|
| `make up` / `make down` | start the stack in the background (waiting until healthy) / stop it, keeping volumes |
| `make build` / `make logs` / `make worker-logs` | build the images / follow the logs / follow both workers (turns and tool jobs) |
| `make shell` / `make psql` | a shell in the `api` container / a `psql` shell in `db` |
| `make warm` | download the read-across encoder into its volume ahead of the first assessment |
| `make test` / `make lint` / `make check` | unit tests / ruff / everything pre-commit enforces |
| `make eval` / `make catalogue` | agent evaluations / the catalogue through the live agent (OpenAI key, costs tokens) |
| `make migrate` | apply the database migrations |
| `make db` / `make test-db` | PostgreSQL on `127.0.0.1:5432` / the PostgreSQL tests |
| `make redis` / `make test-redis` | Redis on `127.0.0.1:6379` / the Redis tests |

## Local development with uv

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and clone this repository.
2. `cp .env.example .env` and fill it in (as above; add `OPENAI_API_KEY` for the command line).
3. `uv sync`, then `uv run pytest`.

The command line runs one assessment without the web stack:

```bash
uv run python -m app "Assess CAS 71-43-2"
```

The chat model is configured once, `[agent]` in `config/settings.toml`; how to swap the provider:
[agent/](../agent/README.md#swapping-the-llm-provider). The web program and its hot-reload set-up:
[api/](../api/docs/running-and-testing.md#running-it) and [frontend/](../frontend/README.md#running-it).
