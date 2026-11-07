# app/ rules

Project-wide guidance is in the root `CLAUDE.md`; these rules apply to work in `app/`.

- The program's outer edge: build the configured chat model and run the agent. No domain
  logic (that is `tools/`) and no graph wiring (that is `agent/`).
- `chat_model.py` is the only module that imports a chat provider package (lazily, chosen by
  `[agent].provider`). The program and `evals/` both build the agent's model through it, so
  they always run the same model; never construct a chat model anywhere else.
- Model name, key variable, timeout and step limit come from `[agent]` in
  `config/settings.toml`; never hard-code them.
- Tests inject a fake environment or a fake chat model; never call a real provider.
- `telemetry.py` is the only place that touches Logfire: `configure_telemetry` runs once at
  start-up (after `.env` is loaded; `app/__main__` and `api/__main__` call it), `session_span`
  wraps a run and `run_tracer` is the callback that records its model and tool calls inside it.
  `agent/` and the tools know nothing about it. `usage_meter.py` is the one place calls are
  counted and priced (CLI summary, web usage meter and span attributes all use it). Span and
  attribute names come from `[telemetry]`; keys and tokens are scrubbed from spans with the same
  patterns as the logs (`commons/key_patterns.py`). `ask` returns a `RunResult` (answer and calls).
- `key_vault.py` is the only module that touches the OS credential store (`keyring`), for the
  OpenAI, Census and CompTox keys (`ServiceKeys`, one entry each from `[ui.keyring]`). A key
  leaves it only as a `SecretStr`: the OpenAI one to `build_chat_model(..., api_key=...)`, all
  of them to the tools through `run.stored_keys_provided`. The program uses the stored keys and
  falls back to each key's environment variable for headless runs. `EnvironmentVault` (same
  `KeyVault` protocol) reads a key from its variable and never stores one; the web program
  uses it only in container mode. `app` never imports `api` (`tests/test_layering.py`).
- `turns/` is the one turn runner. `execute_turn(request, services, settings)` yields
  transport-neutral `TurnEvent`s (frozen dataclasses: no sequence numbers, labels, user-facing
  text or wire schemas) and owns key provision for the turn (`keys.provided`, released on
  every exit), agent build, run config, callbacks, the session span, usage recording and
  failure classification (`failures.FailureReason`, a closed set; never exception text). Its
  collaborators come in as `TurnServices` (key loader, model factory, checkpointer, the user's
  values, usage store). Every front end runs turns only through it; a caller's own failure while
  presenting an event is thrown back in (`athrow`) and reported as the turn's failure.
- `redaction.py` is the one log-redaction filter (`protect_secrets`, `redact`,
  `install_redaction`); it holds no HTTP knowledge. Front ends only configure their loggers.
