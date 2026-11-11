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
- `key_vault.py` is the only module that touches the OS credential store (`keyring`), and it is for
  the command line and the evaluations only: the OpenAI, Census and CompTox keys (`ServiceKeys`, one
  entry each from `[ui.keyring]`), each falling back to its environment variable for headless runs.
  A key leaves it only as a `SecretStr`. `EnvironmentVault` reads a key from its variable and never
  stores one. The web program uses neither keychain nor `ServiceKeys`.
- `user_key_vault.py` is the only module that decrypts a user's OpenAI key (`UserKeyVault`: `save`,
  `clear`, `status`, and `read(user_id)`, the one per-turn decrypt that the API runner and a
  background worker both call). AES-256-GCM through `commons.sealed_secret`; the key-encryption key
  comes from the variable named in `[byok]`, a previous one is accepted during a rotation (lazy
  re-seal on read, `rotate` for the rest); an unreadable row is absent, logged by user id only.
  `operator_keys.py` reads the Census and CompTox keys from the environment once. `app` never
  imports `api` (`tests/test_layering.py`).
- `turns/` is the one turn runner. `execute_turn(request, services, settings)` yields
  transport-neutral `TurnEvent`s (frozen dataclasses: no sequence numbers, labels, user-facing
  text or wire schemas) and owns key provision for the turn (`keys.provided`, released on
  every exit), agent build, run config, callbacks, the session span, usage recording and
  failure classification (`failures.FailureReason`, a closed set; never exception text). Its
  collaborators come in as `TurnServices` (key loader, model factory, checkpointer, the user's
  values, usage store). Every front end runs turns only through it; a caller's own failure while
  presenting an event is thrown back in (`athrow`) and reported as the turn's failure.
  `TurnRequest(resume=True)` continues the thread's checkpoint with no input (fresh step budget;
  `pending_steps` says what would run next); a new message first answers tool calls an abandoned
  turn left without a result (`history.py`). `failures.resumable` names the reasons that
  interrupt a turn instead of failing it.
- Background turns (shared by the API and `worker/`, which never import each other):
  `task_queue.py` (`build_celery`, `TurnJob` ids-only payload, `CeleryEnqueuer` by task name,
  `InProcessEnqueuer` for `[worker].eager` and tests), `turns/bus.py` (per-turn event stream:
  `RedisStreamBus`, `MemoryBus`, one `TurnEventBus` protocol), `turns/codec.py` (relayed events
  as JSON records; `TurnFailed` never travels, `TurnStopped` does; decoded as untrusted),
  `turns/recording.py` and `turns/job.py` (`run_background_turn`: the only writer of a running
  turn's state: status, stored tool messages, pending request, usage, refund, lease; it checks a
  cancel request and the soft time limit after each graph step, renews the heartbeat and lease,
  and publishes the end only after the final status is stored and the lease released).
  `web_turn.py` builds the web turn settings (guards, prompt, prices) for both processes;
  `process_secrets.py` lists the secret variables both protect.
- `redaction.py` is the one log-redaction filter (`protect_secrets` per turn, `protect_for_process`
  for the life of the process, `redact`, `install_redaction`); it holds no HTTP knowledge. Front
  ends only configure their loggers. `telemetry.scrubbing_options(settings, protected)` hides the same
  values in spans; the protected values must be known when Logfire is configured.
