[← Documentation index](../../README.md#documentation) · [API](../README.md)

# Running, contract and testing

## Running it

    npm --prefix frontend ci && npm --prefix frontend run build   # the API serves frontend/dist
    make db && make migrate && make redis                          # PostgreSQL :5432 and Redis :6379 (Docker)
    uv run python -m api                                           # http://127.0.0.1:8000
    uv run celery -A worker.celery_app worker --loglevel=INFO      # another terminal: runs the turns

The server listens on loopback only (`[ui]` in `config/settings.toml`). It needs PostgreSQL: it reads
the connection URL from `DATABASE_URL` (see `.env.example`) and refuses to start when it is missing,
unreachable or not migrated, naming `make migrate`. For the whole stack in containers use
`docker compose --profile dev up --build` (see the root README). Frontend work with hot reload:
[frontend](../../frontend/README.md#running-it).

`GET /api/health` answers `{"status": "ok"}` only while the server is up and PostgreSQL answers, and
503 `{"status": "unavailable"}` otherwise; the container health check uses it.

## Contract with the frontend

`api/schemas/` is the single wire contract with `frontend/`. After changing it run:

    uv run python -m scripts.export_contract
    npm --prefix frontend run gen:types

`npm --prefix frontend run check` fails when the committed contract differs from the schemas.

## Testing

Tests mirror the layout under `tests/api/`. They build the app with in-memory stores and a fake
chat model (`tests/api/auth_support.build_app`), so they never touch PostgreSQL, Redis or a provider.

    uv run pytest tests/api
