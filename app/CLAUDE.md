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
- `jobs/` is the one background tool job runner (task 2.2), mirroring `turns/job.py`:
  `run_background_job(ToolJob, JobServices)` claims the job, runs its tool (`JobServices.runners`,
  from `agent.jobs`) on a thread with a `should_stop` check, supervises heartbeat, cancel flag, soft
  limit (`[worker.tools]`) and the hard-limit backstop, and stores the result (`result.py`: strict
  JSON, redacted) or a fixed `JobFailure` code, never exception text. `keys.py` provides the
  operator's Census/CompTox keys only: a job never reads the user's model key and has no vault.
  `recovery.py` is the stale sweep (running jobs with a stale heartbeat, and queued jobs older than
  `[worker].visibility_timeout_seconds`: a lost task message must not hold the cap) and the
  lost-task interrupt. `JobServices.on_job_started`/`on_job_ended` are the seams (default no-op),
  wired in production to `lifecycle.JobLifecycle` (the `job.running`/`job.ended` thread events, then
  `FollowUps.job_ended`), for the runner and the recovery paths alike. `gateway.JobGateway` is the
  `tools.jobs.port.JobPort` the heavy tools use during a turn (`TurnServices.jobs`): it records the job
  under the owner's cap, publishes `job.queued`, enqueues by ids only (a queue that is down leaves the
  job `interrupted`, never queued), and reports status (no result). `task_queue.ToolJob` is the
  ids-only message; `CeleryToolJobEnqueuer` sends it to the tools queue.
- Follow-up turns and the thread stream: `turns/follow_up.py` records, when a job ends (not when the
  user cancelled it), one `waiting` turn per job (`turns.job_id`, unique: at most once) whose input is
  the fixed notice "Background job {id} ({tool}) ended: {status}"; `FollowUps.release_next` takes the
  thread's lease, moves the oldest waiting turn to `queued` and enqueues it on the chat queue. It is
  called in exactly two places: right after recording, and by `turns/job._finish` once a turn has
  released the thread. The run gets the job's result as a tool call and result (`follow_up_messages`,
  untrusted tool output, stored with the thread's tool messages so the workspace fills from the job's
  artifact), skips the scope check (`TurnRequest.automatic`) and is never counted (`counted=False`).
  `turns/thread_bus.py` is the per-thread stream (`thread:{owner}:{thread}:events`, entries numbered by
  the stream, ids and statuses only): `job.queued|running|ended`, `turn.started|ended`.
  `TurnRequest` carries the job scope in the run config (`tools.jobs.port.scope_config`), never in
  tool arguments.
- `redaction.py` is the one log-redaction filter (`protect_secrets` per turn, `protect_for_process`
  for the life of the process, `redact`, `install_redaction`); it holds no HTTP knowledge. Front
  ends only configure their loggers. `telemetry.scrubbing_options(settings, protected)` hides the same
  values in spans; the protected values must be known when Logfire is configured.
- Orphaned follow-ups: `FollowUps.release_orphans` starts the waiting follow-up of every thread with
  one and no live lease (a process died between claiming the lease and activating); the worker's
  `worker_ready` sweep calls it. A job whose cancel was requested records no follow-up, and an
  automatic turn cannot start a job (`tools.jobs.port.is_automatic`: the submitter answers a fixed notice).
