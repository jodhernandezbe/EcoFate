## Why

A full assessment runs dozens of model and tool calls. When the user's OpenAI account runs
out of credits, the key is rejected, the provider rate-limits or fails, or the run reaches the
LangGraph step limit, the turn ends today with an `error` event and the work done so far is
unreachable: the user must ask again, paying again for every model call and waiting again
for every tool. With BYOK (roadmap step 5) running out of credits mid-turn becomes the
normal failure, so a turn that stops for a reason the user can fix must be continuable from
where it stopped.

## What Changes

- Every chat turn gets a durable record in Postgres (`turns` table, from `storage/`):
  `queued`, `running`, `interrupted`, `completed` or `failed`, with an interruption reason,
  a resume count and timestamps. It replaces the in-memory "turn running" set as the
  one-turn-per-thread guard (a partial unique index on the thread's open turn).
- A turn that stops on a recoverable failure becomes `interrupted` with one reason:
  `out_of_credits`, `rate_limited`, `bad_key`, `provider_down` (includes unreachable),
  `step_limit` or `worker_lost` (the process running it stopped). Unexpected exceptions stay
  `failed` and are not resumable.
- New endpoint `POST /api/v1/chat/threads/{thread_id}/resume` streams the same event
  vocabulary. It continues the thread's LangGraph run from its last checkpoint (input `None`),
  so the user's message is not sent again and tool calls that already finished are not
  re-run. A step-limit resume gets a fresh step budget. Resumes per turn are capped by
  `[agent].max_resumes_per_turn` in `config/settings.toml`.
- New stream event `turn_interrupted` (reason, whether it can be resumed, a fixed message)
  before `usage` and `turn_finished`; `turn_started` gains `resumed`. The thread snapshot
  gains `interrupted` so a reloaded page still offers Resume.
- Sending a new message instead of resuming abandons the interrupted turn: its unanswered
  tool calls are closed with "not run" tool results so the history stays valid for the
  provider, and the turn becomes `failed` with reason `superseded`.
- Chat UI: an interrupted turn shows its message with a **Resume** button (and **Open
  Settings** for `bad_key`); the composer stays usable. Wired through `useAgentStream` and
  `chatState`; no dashboard panel changes.
- At start-up, turns left `running` by a stopped server are marked `interrupted`
  (`worker_lost`).

## Capabilities

### New Capabilities

- `resumable-turns`: durable turn status, interruption reasons, resume semantics, the step
  budget and resume cap, abandoning an interrupted turn, start-up recovery.

### Modified Capabilities

- `web-ui-server`: chat-turn streaming gains `turn_interrupted` and `turn_started.resumed`;
  new resume endpoint; snapshot reports an interrupted turn.
- `web-ui-shell`: the copilot chat offers Resume for an interrupted turn.

## Impact

- `storage/` (turn model, repository, Alembic migration), `api/services/agent_runner.py`
  (classify failures, resume entry), `app/turns/failures.py` + `api/services/provider_errors.py` (reason codes next to
  the fixed messages), `api/services/threads.py`, `api/routers/v1_chat.py`, `api/schemas/chat.py`
  (contract export + `gen:types`), `config/settings.toml` + `config/agent.py`
  (`max_resumes_per_turn`), `frontend/src/hooks/useAgentStream.ts`, `chatState.ts`,
  `frontend/src/features/chat/MessageStream.tsx` (Resume control), README, `api/CLAUDE.md`.
- Depends on `migrate-to-postgresql` (Postgres checkpointer and `storage/`). `agent/` is
  unchanged: resume uses the compiled graph's own checkpoint API.
- `add-user-accounts` later adds the owning user to `turns`; `add-daily-rate-limit` counts a
  resume as zero turns; `add-background-agent-worker` runs resumes in the worker.
