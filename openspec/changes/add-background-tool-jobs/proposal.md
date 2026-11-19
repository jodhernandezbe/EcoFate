## Why

Today a whole chat turn (model calls and every tool) runs as one task behind the queue, and a
thread holds one turn at a time: while it runs, a new message on that thread is answered 409.
The heavy work is not the model. In the monitored hexane session the turn took 4 min 48 s and
one tool, `assess_facilities`, took 3 min 52 s of it; each model call took 1–2 s and every other
tool between milliseconds and about a second. So the user waits minutes with a chat that cannot
answer anything, and with one queue a short question from one user waits behind another user's
long assessment. Claude Code shows the experience we want: a long task starts in the background,
the assistant says so at once, keeps talking, and is notified when it finishes.

## What Changes

- **Two queues and worker pools.** Agent turns go to a light `chat` queue; long tool work goes
  to a heavy `tools` queue. Names, concurrency and limits of each come from `[worker]`. A short
  question no longer waits behind someone else's assessment.
- **`assess_facilities` runs as a background job.** The tool call answers at once with a job id
  and status `queued` (every tool call still gets an immediate answer, as the model API
  requires). A PostgreSQL `jobs` table records each job: owner, thread, status (`queued`,
  `running`, `succeeded`, `failed`, `cancelled`, `interrupted`), input, result and timestamps.
  The turn then ends and releases the thread, so the user can keep chatting while the job runs.
- **The agent can say how a job is going.** A new quick tool, `check_job_status`, reports a
  job's status, queue position and elapsed time; the agent describes long work as started, not
  done.
- **An automatic follow-up turn explains the result.** When a job finishes, the system starts a
  turn in that thread that reads the result and answers; the dashboard and map fill from the
  job's result. If another turn is running in the thread, the follow-up waits until it ends.
  The follow-up does not count against the daily quota.
- **A thread-level event stream** lets the open page see job progress and the follow-up turn
  even after the turn that started the job has ended.
- **Unchanged rules:** task messages carry ids only; the worker that needs a key decrypts it
  (the API never decrypts); the missing-value request happens before a job is queued; cancel,
  time limits, heartbeats and "lost becomes resumable" apply to jobs; eager mode runs everything
  in-process for tests. The other 11 tools stay synchronous.
- **A load test** measures the system with many users: a scripted multi-user run against the
  compose stack with a fake chat model and recorded tool latencies (no token cost) at 10, 25 and
  50 concurrent users, then a small run with the real model at about 10 users within a stated
  budget. The results are written to the docs.

## Capabilities

### New Capabilities
- `background-tool-jobs`: heavy tool calls as queued jobs, their record and status, the
  status tool, the follow-up turn and the thread-level stream.
- `load-testing`: the multi-user load test, its scenarios, measurements and reported results.

### Modified Capabilities
- `background-agent-worker`: two queues and pools instead of one; settings per queue.
- `daily-turn-quota`: an automatic follow-up turn is not counted.

## Impact

- Code: `tools/assessment/` (the job-submitting tool), a new `tools` job runner, `app/task_queue.py`
  and `app/turns/` (queues, follow-up turns, thread stream), `worker/` (two task routes), `storage/`
  (jobs table and migration), `api/` (thread stream endpoint, job status in the workspace),
  `frontend/` (job status line and thread stream), `prompts/` and tool docstrings (how to talk
  about a running job), `config/settings.toml` (`[worker]` queues, job limits), `compose.yaml`
  and `compose.prod.yaml` (a second worker service), new load-test scripts under `scripts/load/`.
- Evals: the missing-value and chemical-name-only scenarios must be re-recorded and re-run, since
  the agent's reasoning around `assess_facilities` changes.
- Cost: the load test with the fake model costs nothing; the real-model run is capped by a
  budget the owner sets.
