## Context

See proposal.md for motivation. What the code does today:

- `api/services/agent_runner.py::_turn_events` yields `turn_started`, runs
  `agent.astream(inputs, config, stream_mode=["messages", "updates"])` with
  `inputs = {"messages": [HumanMessage(plan.message)], "answers_note": plan.note}`, and turns
  any exception into one `error` event (`provider_errors.explain` maps provider failures to
  fixed messages: `OUT_OF_CREDITS`, `BAD_KEY`, `RATE_LIMITED`, `UNREACHABLE`,
  `PROVIDER_DOWN`, `FORBIDDEN`), then `usage` and `turn_finished`.
- The graph (`agent/graph.py`) is `scope -> model -> tools -> (ask | model) -> finish`,
  compiled with an injected checkpointer. LangGraph checkpoints after every super-step, so
  when the `model` node raises (429 `insufficient_quota`, 401, 5xx) the last checkpoint holds
  every finished tool result and `get_state(config).next == ("model",)`. On
  `GraphRecursionError` the checkpoint likewise holds the last finished step and `next` is
  non-empty. `astream(None, config)` continues from there without a new input.
- `api/services/threads.py::ThreadStore` keeps `_busy` (one turn per thread) in memory;
  `migrate-to-postgresql` moves history to the Postgres checkpointer and the thread
  metadata (workspace, usage, pending confirmation, answers) to `storage/`.
- The missing-value flow ends a turn at the `ask` node (graph `END`) with a pending
  `ConfirmationRequest`; the next turn carries `answers` and `plan_turn` clears the pending
  request before the turn starts.
- The completion guard counts nudges from the messages of the current user turn, so it
  survives a resume unchanged.

## Goals / Non-Goals

**Goals:**
- A turn stopped by a cause the user can fix continues from its last checkpoint, with no
  repeated user message, no repeated finished tool call, and usage accumulated on the same
  turn.
- Turn status is durable and survives a reload or a server restart.
- The UI says why the turn stopped (fixed text) and offers Resume only when it can work.

**Non-Goals:**
- Automatic retries or backoff (the user decides when to resume; credits need a human).
- Resuming after an unexpected exception (unknown bugs may repeat; fail closed).
- Re-running a single tool or editing history; branching/time travel.
- Running turns off the request (that is `add-background-agent-worker`).

## Decisions

1. **Turn record in `storage/`.** Table `turns(id, thread_id, status, reason, resume_count,
   step_budget_used, created_at, started_at, updated_at, finished_at)` with a partial unique
   index on `thread_id WHERE status IN ('queued','running')`. Claiming a thread is inserting
   that row; a unique-violation answers 409 as today. Alternative: keep the in-memory busy
   set, rejected because a second API process or a worker could not see it.
   *As built:* `migrate-to-postgresql` had already replaced the in-memory set with a
   cross-process lease (`threads.busy_until`), whose expiry the `persistent-storage` spec
   requires. The lease stays the claim, and the turn record sits on top of it. With the lease
   held, a turn still open on the thread is stale and becomes `interrupted/worker_lost` (as at
   start-up), so an expired lease never leaves a thread blocked. A stream the client leaves
   also interrupts its turn (`worker_lost`). `step_budget_used` was not added (LangGraph does
   not report steps used). Each usage row gains a nullable `turn_id`, so a resumed turn's
   usage is the sum of its segments.
2. **Reasons in the runner, messages in the web layer.** `extract-turn-runner` already put
   `classify(exc) -> FailureReason` in `app/turns/failures.py`; this change adds
   `GraphRecursionError` -> `step_limit` and a `resumable(reason)` predicate there, and
   `api/services/provider_errors.py` maps each reason to its fixed message. The wire reason
   set is a `Literal` in `api/schemas/chat.py`. `forbidden` stays a non-resumable `failed`
   (account/model policy, not fixable mid-turn).
3. **Resume is `astream(None, config)` on the same thread id.** Preconditions checked before
   claiming: the thread's latest turn is `interrupted`, `resume_count <
   max_resumes_per_turn`, `get_state(config).next` is non-empty, a key is available. A
   failed precondition answers 409 with a fixed message and changes nothing. If `next` is
   empty (the checkpoint already finished) the turn is marked `completed` and 409 is
   returned. Alternative: replay the user message, rejected (repeats cost and tool calls).
4. **Fresh step budget per resume, capped.** Each resume runs with the configured
   `recursion_limit`; `[agent].max_resumes_per_turn` (default 3) bounds the total so a
   looping agent cannot run forever on resumes.
5. **Abandon on a new message.** If the user sends a message while the latest turn is
   `interrupted`, the runner first calls `graph.update_state` to append a `ToolMessage`
   ("not run: the turn was interrupted and not resumed", status `error`) for each tool call
   of the last `AIMessage` that has no result, then marks the turn `failed/superseded`.
   Without this, OpenAI rejects a history with unanswered tool calls.
6. **Pending confirmation is not an interruption.** A turn that stops at `ask` is
   `completed`; Resume is not offered and the answers flow is unchanged. A turn carrying
   answers that is then interrupted resumes with those answers already recorded (they were
   stored before the turn started), so no answer is asked twice.
7. **Start-up recovery.** On API start, every turn still `running` is set to
   `interrupted/worker_lost` (resumable). The worker change refines this with heartbeats.
8. **UI wiring only through chat state.** `chatState` gains an `interrupted` field on the
   assistant message (`reason`, `resumable`, `message`); `MessageStream` renders the text and
   a Resume button; `useAgentStream.resume()` posts to the resume endpoint and feeds the
   same reducer. The snapshot's `interrupted` restores the button when a held thread is restored (restoring the thread after a page reload is a separate change).
9. **Telemetry.** A resume is its own turn span with `session_id` = thread id plus
   attributes `turn_id` and `resume_index`, so Monitoring shows the segments of one turn.

## Risks / Trade-offs

- A tool that had side effects and raised inside the `tools` node is re-run on resume →
  tools here are read-only HTTP/data lookups; acceptable and documented.
- Parallel tool calls in one `ToolNode` are one task: if the node fails, all its tools re-run
  → tools return errors as results rather than raising, so the node rarely fails.
- `rate_limited` resumed immediately fails again → the message says to wait; the failed
  resume increments the count, and the cap stops a loop.
- Usage of a resumed segment is added to the same turn; the turn total in the UI is the sum.

## Migration Plan

Alembic revision adds `turns`; existing threads have no turns and behave as idle. Rollback:
downgrade the revision; the runner falls back to the error-only behaviour of today only by
reverting the code (no feature flag).

## Open Questions

None blocking. `add-user-accounts` adds `turns.user_id` and the ownership filter.
