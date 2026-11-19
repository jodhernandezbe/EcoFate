[← Documentation index](../README.md#documentation) · [For reviewers](reviewers.md) · [Getting started](getting-started.md)

# Demo: one assessment, start to finish

A walk through a real session, so the app can be judged without an API key. Every screenshot
comes from the running application (v0.2.4) and one question: *"Map hexane (CAS 110-54-3)
releases and compute exposure metrics"*. The turn used 71K tokens of gpt-4.1, about USD 0.11.

- [1. Sign in and get oriented](#1-sign-in-and-get-oriented)
- [2. Ask, and be asked back](#2-ask-and-be-asked-back)
- [3. The agent works](#3-the-agent-works)
- [4. The answer and the dashboard](#4-the-answer-and-the-dashboard)
- [5. Read the results three ways](#5-read-the-results-three-ways)
- [6. Look at the map](#6-look-at-the-map)
- [7. Monitoring](#7-monitoring)
- [8. Evaluation results](#8-evaluation-results)

## 1. Sign in and get oriented

Each user has an account and brings their own OpenAI key
([accounts](../api/docs/accounts-and-email.md), [keys](../api/docs/keys-and-byok.md)).

![The sign-in screen](images/01-sign-in.png)

The first visit opens a welcome card with the three things to know: bring your key, ask in plain
words, read the results.

![The welcome card shown on a first visit](images/02-welcome.png)

## 2. Ask, and be asked back

The user asks about hexane. The agent looks the chemical up first and finds that no source has
an inhalation unit risk for it, the benchmark a cancer risk needs. It stops before assessing
anything and asks: enter the value with its unit, or proceed without it. Nothing is guessed
([how it decides](../agent/README.md)).

![The agent asks for the missing inhalation unit risk before assessing anything](images/03-asks-missing-value.png)

## 3. The agent works

The user proceeds without the value. The turn runs in a background worker; the chat shows the
step in progress and a Stop button, and a reload would pick the same turn up again
([worker](../worker/README.md)).

![The turn running: the current step and the Stop button](images/04-turn-running.png)

## 4. The answer and the dashboard

About five minutes later the answer arrives: 1,255 facilities reporting hexane releases were
screened and 157 have a worst-case result. The chat
gives the summary, a results table, comments and limitations; the overview and the map fill in
from the same results. The cancer risk reads "Not computed", because the value the user declined
stays absent.

![The workspace after the answer: overview, map and chat](images/05-answer-and-dashboard.png)

## 5. Read the results three ways

**Summary:** the worst-case and representative hazard quotient for the community, and the worker
screening, each with its band in words and the facility that drives it.

![The overview's Summary tab](images/06-overview-summary.png)

**Risk by group:** the highest worst-case value by industry, by TSCA condition of use and by life
cycle stage, against the moderate and high thresholds.

![The Risk by group tab: bars by industry, condition of use and life cycle stage](images/07-risk-by-group.png)

**Exposure chain:** how the worst case arises, from the reported release through the air pathway
and the inhalation route to the receptor and the risk, for the community and for workers.

![The Exposure chain tab: source, release, pathway, route, receptor and risk](images/08-exposure-chain.png)

## 6. Look at the map

Every facility is a marker: its size is the annual air release, its colour the screening band of
the chosen pathway. The legend counts each band (74 high, 83 moderate, 1,073 low).

![The map of facilities coloured by screening band](images/09-map.png)

A click opens the facility: identifiers, industry, bands, reported release, conditions of use,
stacks and its worst-case scenarios.

![The inspector of one facility, with its hazard quotient and scenarios](images/10-facility-inspector.png)

## 7. Monitoring

Every turn is traced to Logfire. An administrator sees the recorded sessions with their estimated
cost and status ([monitoring](monitoring.md)).

![The admin Monitoring view: recorded sessions with cost and status](images/11-monitoring-sessions.png)

Opening a session shows its timeline: each model call with its tokens, each tool call with its
duration, and a link to the full trace. This is the session above: the first turn stops after
the chemical lookup; the second runs the batch assessment.

![A session's timeline: model calls and tool calls of each turn](images/12-monitoring-session-detail.png)

## 8. Evaluation results

The scripted scenarios replay recorded tool outputs against the real chat model and check what
the agent did. This is the report of the "missing benchmark" scenario, the behaviour shown in
step 2: the run completed, the properties were looked up, no exposure was computed, and the
agent asked for the unit risk ([scenarios](../evals/docs/scenarios.md)).

![An evaluation report: every check of the missing-benchmark scenario passed](images/13-evaluation-report.png)

The LLM judge that scores full answers was tuned against 50 labelled answers over six prompt
iterations ([judge tuning](../evals/docs/judge-tuning.md)):

| Judge prompt | Accuracy | Precision | Recall |
|---|---|---|---|
| Baseline | 0.68 | 0.53 | 1.00 |
| Iteration 4 | 0.72 | 0.58 | 1.00 |
| Iteration 6 (kept) | 0.78 | 0.64 | 0.95 |
