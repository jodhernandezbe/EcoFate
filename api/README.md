[← Documentation index](../README.md#documentation) · [Architecture](../docs/architecture.md) · [Security](../docs/security/README.md) · [Worker](../worker/README.md)

# api/

The local and production web backend: FastAPI with server-sent events (SSE). It is a thin transport,
security and state-serialisation layer over the agent core: it authenticates the user, queues each
chat turn for the [worker](../worker/README.md), relays the turn's events, and serves the built
React app. It never runs the agent and never duplicates physics or EPA queries (those live in
`tools/` and `models/`). Rules for coding agents: `api/CLAUDE.md`.

## Contents

- [Layout](#layout) (below)
- [Running, contract and testing](docs/running-and-testing.md): start the stack, the frontend contract, the tests
- [Endpoints, streaming and the daily limit](docs/endpoints-and-streaming.md): every route, the SSE turn stream, the per-user daily turn limit
- [Accounts and email](docs/accounts-and-email.md): sign-up, sessions, administrators, SMTP in development and production
- [Keys and BYOK](docs/keys-and-byok.md): the user's encrypted OpenAI key, operator keys, the key-encryption key and its rotation

## Layout

    api/
      main.py                app factory: own-origin CORS, Origin/Host guard, sanitised errors, static frontend
      __main__.py            python -m api [--container | create-admin | rotate-keys]
      routers/               thin handlers, one module per area (v1_auth, v1_account, v1_chat, ...)
      services/              orchestration: agent_runner (relays a turn's events), auth/, threads,
                             quota, turn_queue, turn_lifecycle, workspace_sync, report/,
                             exposure_graph/, monitoring/
      schemas/               every wire model (the single contract with frontend/)
      core/                  config view, origin guard, session guard, log filter, exception handlers

Routers call services and services call the agent core; routers hold no logic.
