## 1. Settings and storage

- [ ] 1.1 Add `max_resumes_per_turn` (positive int, default 3, with a comment) to `[agent]` in `config/settings.toml` and `AgentSettings` in `config/agent.py`; negative tests for 0, negative and `bool` values in `tests/config/`.
- [ ] 1.2 Add the `Turn` model and `TurnRepository` to `storage/` (create/claim with the partial unique index, mark running/interrupted/completed/failed, latest turn of a thread, increment resume count, mark stale running turns interrupted) and an Alembic revision; tests against the test database including the unique-violation claim and an illegal transition (e.g. `completed -> running`) rejected.

## 2. Classification and runner

- [ ] 2.1 In `app/turns/failures.py` (from `extract-turn-runner`): map `GraphRecursionError` to `step_limit`, fold `unreachable` into `provider_down`, add `resumable(reason)` (`forbidden` and `unexpected` are not); in `api/services/provider_errors.py` add the fixed messages for the new reasons; tests per status/code and a negative test that an unknown exception is `unexpected` and not resumable.
- [ ] 2.2 Add `turn_interrupted` (reason, resumable, message) and `turn_started.resumed` to `api/schemas/chat.py`, `interrupted` to `ThreadSnapshot`; run `uv run python -m scripts.export_contract` and `npm --prefix frontend run gen:types`.
- [ ] 2.3 In `app.turns.execute_turn` and the `agent_runner` presenter: record the turn row; on a classified failure mark `interrupted` and emit `turn_interrupted` (still followed by `usage` and `turn_finished`); on an unclassified one mark `failed` and keep the generic `error`.
- [ ] 2.4 Add `resume_turn(thread_id, ...)`: check preconditions (latest turn interrupted, under the cap, checkpoint `next` non-empty, key present), then `astream(None, config)` with a fresh `recursion_limit`; emit `turn_started(resumed=True)`; usage accumulates on the same turn. Tests with a fake model that raises a 429 `insufficient_quota` on its second call: the resume makes no new `HumanMessage`, re-runs no finished tool (counted by a fake tool), and finishes the answer.
- [ ] 2.5 Abandon on a new message: close unanswered tool calls with "not run" `ToolMessage`s via `update_state`, mark `failed/superseded`; test that the next model call receives a history with every tool call answered.
- [ ] 2.6 Start-up recovery in the API lifespan: running turns -> `interrupted/worker_lost`; test.

## 3. Endpoint

- [ ] 3.1 `POST /api/v1/chat/threads/{thread_id}/resume` in `api/routers/v1_chat.py` (thin; SSE like `/stream`); negative tests: unknown thread 404, nothing to resume 409, cap reached 409, turn already running 409, malformed id 422; none of them changes the turn.
- [ ] 3.2 Snapshot reports the interrupted turn (`reason`, `resumable`, `message`); test.

## 4. Frontend

- [ ] 4.1 `chatState.ts`: handle `turn_interrupted` (assistant message keeps its partial text, gains `interrupted`, streaming stops, status indicator shows the stop); reducer tests including a resumed stream that appends to the same message.
- [ ] 4.2 `apiClient.ts` `resumeChat(threadId)` and `useAgentStream.resume()`; restore from snapshot `interrupted`.
- [ ] 4.3 `MessageStream.tsx`: under an interrupted message show its fixed text and a **Resume** button (disabled with a reason while a turn runs, hidden when not resumable), plus **Open Settings** for `bad_key`; component tests for each reason; follow `frontend/DESIGN.md` and run `/ui-check` (light and dark).

## 5. Documentation

- [ ] 5.1 README (web interface: what Resume does and when it appears), `api/CLAUDE.md` (turn status and resume rules), the root `CLAUDE.md` if a dependency line changes (stay within its line budget).

## 6. Verification

- [ ] 6.1 `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, `uv run bandit -c pyproject.toml -r agent app api commons config evals models prompts tools storage`, the function-length check, `npm --prefix frontend run check`, `uv run pre-commit run --all-files` (twice).
- [ ] 6.2 One live check with a real key: start an assessment with `recursion_limit` temporarily lowered in a local settings override so it hits the step limit, press Resume, confirm the answer completes, the tool pills of the first segment are not repeated, and Logfire shows two turn spans with the same thread id. Restore the setting.
