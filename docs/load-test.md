[← Documentation index](../README.md#documentation) · [All docs](README.md)

# Load test

How EcoFate behaves with many users at once, now that a full assessment runs as a
background job. Measured on 2026-11-19 on the local compose stack, which is the same
containers that run on ecofate.org.

## Contents

- [What was measured](#what-was-measured)
- [How to run it](#how-to-run-it)
- [Scripted runs (no cost)](#scripted-runs-no-cost)
- [Real-model run](#real-model-run)
- [What the evaluations found](#what-the-evaluations-found)
- [Reading: where the limit is](#reading-where-the-limit-is)

## What was measured

Each simulated user signs in through the real API and has one conversation:

1. Asks for an assessment, which is queued as a background job.
2. Asks a short question while the job runs.
3. Asks for the job's status.
4. Waits for the automatic follow-up turn that explains the result.

An interrupted turn is resumed once. Users start spread over a ramp. Every time is taken from
the client's side, through the API and the two event streams. Job times come from the thread
stream's own entry ids, so they are server time.

| Measurement | Meaning |
|---|---|
| Time to first answer | From sending a message to its first answer text |
| Queue wait, chat | From sending a message until a chat worker starts the turn |
| Queue wait, tools | From `job.queued` to `job.running` |
| Job duration | From `job.running` to `job.ended` |
| Follow-up start | From `job.ended` to the follow-up's `turn.started` |
| 409 / 429 / 5xx | Share of requests answered busy, over quota, or failed |
| CPU, memory | `docker stats` every 5 s, peak and mean per service |

## How to run it

```
LOAD_FAKE_MODEL=1 docker compose -f compose.yaml -f compose.load.yaml --profile dev up -d --build
uv run python -m scripts.load.run --users 10            # also 25 and 50
```

`compose.load.yaml` makes four changes, and is local only (never production):

- It mounts `scripts/` and the load profile (`scripts/load/settings.load.toml`, which turns the
  background job on, sets the pool sizes and raises the daily quota).
- It sends verification emails to Mailpit.
- It starts both workers through `scripts.load.worker`.
- With `LOAD_FAKE_MODEL=1`, the worker uses a scripted chat model, and the assessment waits for
  its recorded time (`scripts/load/timings.toml`). Nothing calls OpenAI or an external data
  service.

The recorded latencies come from the Logfire trace of one full assessment turn:

| Step | Recorded time |
|---|---|
| The assessment (`assess_facilities`) | 232 s |
| Its preflight lookups | 3 s |
| One model call | 2 s |

The real-model run needs `LOAD_FAKE_MODEL=0` and:

```
uv run --env-file .env python -m scripts.load.run --users 10 --real --budget-usd 6
```

It saves the key from `OPENAI_API_KEY` for each test account, through the local API only. It
starts no new turn once the estimated cost reaches the budget. Reports go to
`scripts/load/reports/<time>-<users>u-<mode>/` (ignored by git).

## Scripted runs (no cost)

Local Docker: 14 CPUs, 7.7 GiB. Every run lasted at most 20 minutes.

**Pools of 2 chat and 1 tools (the local defaults)**

| Measurement (median / p95, s) | 10 users | 25 users | 50 users |
|---|---|---|---|
| Time to first answer, assessment request | 19.4 / 35.7 | 61.3 / 114.8 | 127.8 / 248.1 |
| Time to first answer, question during a job | 26.3 / 35.9 | 87.6 / 113.4 | 194.2 / 249.2 |
| Queue wait, chat queue | 17.4 / 30.6 | 71.1 / 107.7 | 164.8 / 239.0 |
| Turn duration, user turns | 26.6 / 37.8 | 79.2 / 115.4 | 172.9 / 245.9 |
| Queue wait, tools queue | 453 / 1135 | 456 / 1140 | 453 / 1137 |
| Job duration | 232 / 232 | 232 / 232 | 232 / 232 |
| Jobs ended in the run | 5 of 10 | 5 of 25 | 5 of 50 |
| 409 / 429 / 5xx | 0 / 0 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % |
| Worker (chat) CPU peak, memory peak | 204 %, 530 MiB | 280 %, 532 MiB | 185 %, 532 MiB |

**Pools of 8 chat and 2 tools, 50 users**

| Measurement (median / p95, s) | 2 chat / 1 tools | 8 chat / 2 tools |
|---|---|---|
| Time to first answer, assessment request | 127.8 / 248.1 | **28.0 / 48.7** |
| Time to first answer, question during a job | 194.2 / 249.2 | **36.1 / 48.9** |
| Queue wait, chat queue | 164.8 / 239.0 | **26.4 / 41.3** |
| Jobs ended in 20 min | 5 | **10** |
| Follow-up start after job end | 0 / 343 | **0 / 0** |
| Worker (chat) memory peak | 532 MiB | 1,179 MiB |

No run had a 409: nobody was locked out of their conversation while a job ran. That was the
point of the change, since before it the thread stayed busy for the whole assessment.

## Real-model run

10 users, the real model (gpt-4.1) and the real tools and data services. The run took 30
minutes at most and had a USD 6 cap. Pools were 3 chat and 1 tools: with local Docker's
7.7 GiB, more slots would not fit the PyTorch children. Every user asked about vinyl
chloride (CAS 75-01-4).

| Measurement | n | Median | p95 | Max |
|---|---|---|---|---|
| Time to first answer, assessment request (s) | 10 | 7.3 | 20.6 | 20.6 |
| Time to first answer, question during a job (s) | 10 | 5.8 | 12.5 | 12.5 |
| Time to first answer, status question (s) | 10 | 7.9 | 20.4 | 20.4 |
| Queue wait, chat queue (s) | 30 | 2.3 | 13.1 | 13.3 |
| Turn duration, user turns (s) | 30 | 10.7 | 23.6 | 25.5 |
| Queue wait, tools queue (s) | 10 | 88.9 | 181.3 | 181.3 |
| Job duration (s) | 10 | 18.1 | 44.8 | 44.8 |
| Follow-up start after job end (s) | 10 | 0.0 | 35.6 | 35.6 |
| Follow-up turn duration (s) | 10 | 25.7 | 29.7 | 29.7 |

- **Requests:** 30 in all, with 0 % answered 409, 429 or 5xx.
- **Jobs:** 10 queued and 10 succeeded, and all 10 follow-up turns explained their result.
- **Cost:** an estimated USD 1.19.
- **Resources (peak):** the chat worker reached 196 % CPU and 1,192 MiB; the tool worker
  reached 203 % CPU and 718 MiB.
- **Caching:** the first job took 45 s, and the rest reused the cached TRI, NEI, weather and
  Census answers. A job for a chemical nobody asked about before takes minutes, like the 232 s
  the scripted runs replay.
- **Responsiveness:** a question asked while an assessment runs is answered in about 6 s. With
  synchronous turns it waits behind the whole assessment.

## What the evaluations found

The evaluations were run with background jobs on (`evals/docs/scenarios.md`). They changed
the design four times:

1. **The status tool is offered only when a job exists.** Offering `check_job_status` in every
   turn made the model write a CAS number from memory when the user gave only a chemical's name.
   With the tool it failed 5 and 6 of 10 runs; without it, the same as `main`. The tool now joins
   a turn only once its conversation has a job (`agent.graph.turn_tools`), so a turn with
   nothing to check has exactly `main`'s tools. Measured afterwards: 17 of 20 on both `main` and
   this branch, an existing 15 % miss that this change neither causes nor fixes.
2. **The batch tool keeps its own description.** A paragraph saying the call "does not run the
   work" made the model assess vinyl chloride's facilities one by one, 0 of 3 runs. That is
   the long turn the job exists to avoid; `main` used the batch tool 3 of 3. The description is
   the tool's own again, and the guidance on a running job comes in the queued answer's `note`.
3. **No completion review after queuing.** The completion check read "it has started" as an
   announcement and sent the agent back to work it did not have. In one run the agent then
   wrote a table of results it had never seen. A turn that queued a job is now not reviewed
   (`agent.completion.queued_a_job`; only a heavy tool's queued answer counts).
4. **No paragraph about background work in the system prompt.** It was redundant with the tool
   guidance, so it was removed.

Results after the changes:

| Scenario | Result |
|---|---|
| `assessment-queued-then-explained` (vinyl chloride, 33 facilities) | 3 of 3 |
| `missing-benchmark-asks` | 3 of 3 |
| `chemical-name-only` | 10 of 10, then 7 of 10 (`main`: 10 of 10, then 7 of 10) |

Two problems were found that this change did not cause. Both appear on `main`, and both are
left for their own changes:

- With 33 facilities, the report lists the highest 21 and leaves 15 assessed facilities out,
  the same 15 in the synchronous run.
- With only two facilities (1,2-dibromo-3-chloropropane), the agent assesses them by hand, so
  no job starts. That turn is short anyway.

## Reading: where the limit is

- **Chat slots set the wait for a reply.** Each turn holds a slot for its model calls, so the
  chat-queue wait grows with users per slot: 2 slots gave a 165 s median wait at 50 users,
  and 8 slots gave 26 s. CPU stayed under two cores. Memory is what limits the slot count: a
  chat child that runs the read-across tool loads PyTorch (about 1.5 GB).
- **Tools slots set the job throughput.** One slot finishes about 15 assessments of 232 s an
  hour; two finish about 30. When more jobs are queued, they wait. They don't fail, and the
  conversation stays usable meanwhile.
- **Production setting.** The Oracle VM has 4 OCPUs and 24 GB. That fits `[worker.chat]` 4 and
  `[worker.tools]` 2 (`config/settings.production.toml`), with memory limits of 10 GB and 6 GB
  (`compose.prod.yaml`). At 50 users the expected chat wait is between the 2-slot and 8-slot
  runs, about a minute. More tools slots would need more memory.
