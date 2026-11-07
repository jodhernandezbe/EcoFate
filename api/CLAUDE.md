# api/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `api/`.

- A thin HTTP/SSE transport, security and state-serialisation adapter over the agent core.
  Never duplicate physics, EPA queries or read-across math here; those live in `tools/` and
  `models/`. If the UI needs a new fact, it needs a tool, not an `api/` function.
- Layering: `routers/` (thin handlers, no logic) -> `services/` (orchestration: agent runner,
  state serializer, threads, usage) -> the agent core. `core/` holds config view, keyring,
  log redaction and exception handlers; `schemas/` holds every wire model.
- Allowed imports: `app`, `agent`, `config`, `commons`, `prompts`, `tools.schemas` (types
  only) and `tools.credentials` (to give the turn's keys to the tools that need them). Never import tool modules, provider packages or `evals`; nothing imports `api`.
- Settings come from `[ui]` in `config/settings.toml` via `config.ui`; `api/core/config.py`
  only exposes them to `Depends()`. Never read ports, origins or names from the environment.
  The container bind address comes only from `[ui.container]`, used when `python -m api
  --container` runs; the origin checks always use `[ui].host:[ui].port`, whatever is bound.
  `GET /api/health` (liveness for container health checks) reads no key and runs no agent.
- The chat model is built only through `app.chat_model`. The OpenAI, Census and CompTox keys
  are read once per turn from `app.key_vault.ServiceKeys`, given to the tools through
  `tools.credentials.HOLDERS` for that turn only, protected from the logs, and never stored on
  anything that outlives the turn. Only the OpenAI key is required.
- `api/schemas/` is the single wire contract with `frontend/`. After changing it run
  `uv run python -m scripts.export_contract` and `npm --prefix frontend run gen:types`.
- Responses, events and logs never contain exception text, request headers or key material;
  log through the redaction filter and return a generic message with a correlation id.
- The workspace shows only what tools returned: never compute, estimate or convert values
  (geometry for drawing the buffer and schematic sector is the one exception); anything
  unverified or unattributable becomes absent with a reason.
- `services/exposure_graph/` turns each validated `Facility` into its `exposure_graph` (source, one
  lane per pathway, nodes and edges with value, unit and source or a reason). It only rearranges
  values; a lane is one module in `LANES`; its fixed text and units are `[ui.exposure_graph]`.
- `services/report/` writes a thread's Word report (one module per section) from its
  `WorkspaceState` and last assistant message only: it formats values (`values.py`, the same text
  as the dashboard) and never computes one; its fixed text is `[ui.report]`.
- `services/monitoring/` reads recorded sessions back from the Logfire query API for the
  Monitoring view (`client.py` the only module that talks to it, `queries.py` the SQL, `rows.py`
  the untrusted-row parsers, `sessions.py` and `timeline.py` the figures, `service.py` the states).
  The read token comes from the environment variable named in `[telemetry]`, never from the
  user or the keychain; it is used only there, protected from the logs, and never returned or
  given to the agent. Statements take values only as quoted literals (ids match
  `THREAD_ID_PATTERN`). Everything shown comes from the spans; a missing figure is absent, and
  Logfire failures are a state with a user-safe message, never invented sessions.
- Tests mirror the layout under `tests/api/`; they inject a fake vault, a fake chat model and
  an in-memory keyring backend and never touch the real keychain or a real provider.
