[← Documentation index](../README.md#documentation) · [Architecture](architecture.md) · [Security](security/README.md)

# Monitoring

Every run of the agent can be recorded as a trace in
[Pydantic Logfire](https://logfire.pydantic.dev) and read back in the web interface's
**Monitoring** view, which only administrators see.

## Contents

- [What a session records](#what-a-session-records)
- [Set-up](#set-up)
- [How the data flows](#how-the-data-flows)
- [Redaction](#redaction)
- [Opening the dashboard](#opening-the-dashboard)
- [Switching it off](#switching-it-off)

## What a session records

One session per command-line run (`uv run python -m app "..."`, span `assessment session`) or per
chat turn of the web interface (span `assessment turn`, tagged with the conversation; the API's
enqueue span is `assessment turn queued`). The span names and attribute names are in
`[telemetry.spans]` and `[telemetry.attributes]` in `config/settings.toml`; they are the contract
between what the telemetry writes and what the Monitoring view queries.

A session holds:

- every model call (prompt, answer, tokens) and every tool call (name, arguments, result,
  duration), as child spans written by the LangChain-to-OpenTelemetry bridge in `app/telemetry.py`;
- the run's token counts and estimated cost, priced with the same `[ui.pricing]` table as the
  chat's usage meter (`app/usage_meter.py` is the one place calls are counted and priced); the
  command-line program prints the cost after the answer, on stderr, so the answer can still be piped;
- the question, the model name, the outcome, the turn id, the resume index, how long the turn waited
  in the queue (web turns), and the signed-in user's opaque id (`enduser.id`, never the email).

## Set-up

Done once, by whoever installs the app, in the environment, never in the interface. Both tokens
come from one Logfire project (Settings -> Write tokens / Read tokens):

    LOGFIRE_TOKEN=...        # lets runs send their traces; without it nothing leaves the machine
    LOGFIRE_READ_TOKEN=...   # lets the Monitoring view read them back

- **Locally:** put them in `.env` (the variable names are `write_token_env_var` and
  `read_token_env_var` in `[telemetry]`).
- **In production:** the VM's `/opt/ecofate/.env.prod` needs both `LOGFIRE_TOKEN` and
  `LOGFIRE_READ_TOKEN` (the template is `deploy/env.prod.example`, and both are empty there by
  default). Without the write token no traces are sent; without the read token the Monitoring view
  says so and shows nothing else. See [deployment](deployment/first-login-and-secrets.md#4-first-login-and-the-secret-files).

The production settings overlay sets `[telemetry].environment = "production"`. Production uses its
own Logfire project (its own pair of tokens), so its traces never mix with development's: look
for them in that project, not in the one a developer's `.env` points at.

## How the data flows

1. **Writing:** each agent run records spans through `app/telemetry.py`, which sends them to Logfire with the write token.
2. **Reading:** an admin opens Monitoring, the browser calls `GET /api/v1/monitoring/sessions` (or `/sessions/{id}`), and `api/services/monitoring/` asks the Logfire query API with the read token, then turns the rows into sessions and timelines.

`app/telemetry.py` is the only module that touches Logfire for writing: `configure_telemetry` runs
once at start-up, `session_span` wraps a run and `run_tracer` records the model and tool calls
inside it. `agent/` and the tools know nothing about it.

For reading, `api/services/monitoring/` is the only code that talks to the Logfire query API:
`client.py` the connection, `queries.py` the SQL (values enter a statement only as quoted
literals, and session ids must match a fixed pattern), `rows.py` the parsers of the untrusted
rows, `sessions.py` and `timeline.py` the figures, `service.py` the states. Everything shown
comes from the spans; a missing figure is absent, never invented. The account's email is looked
up in the application database, not in Logfire.

The view has four states (`ok`, `not_configured`, `unavailable`, `unauthorized`); when it is not
`ok` it shows a user-safe message and no sessions. Limits come from `[telemetry]`:
`session_window_hours` (168), `max_sessions` (50), `max_rows` (2000) and `query_timeout_seconds`.

## Redaction

- When a write token is set, questions, tool arguments and results (chemical identifiers,
  facility data) are sent to Logfire.
- API keys and tokens are scrubbed from every span with the same patterns as the logs
  (`commons/key_patterns.py`), plus the exact secret values the process holds
  (`app/redaction.py`, `telemetry.scrubbing_options`). The values must be known when Logfire is
  configured.
- The read token is read from the environment only, protected from the logs, never returned by an
  endpoint and never given to the agent.
- The tests never send anything.

More on how secrets are handled: [security](security/redaction-and-threats.md#redaction-and-logs).

## Opening the dashboard

- **Check a trace from the command line:**
  `uv run python -m app "What is the molecular weight of benzene, CAS 71-43-2?"`, then open the
  project in Logfire (Live view).
- **Locally:** sign in as an administrator (create one with
  `uv run python -m api create-admin --email <address>`, or
  `docker compose exec api python -m api create-admin --email <address>`) and open **Monitoring**
  in the left rail. Everyone else gets the 404 of an unknown page.
- **In production:** the same view at `https://ecofate.org`, as an administrator.
- The view lists recorded sessions with their model calls, tool calls, tokens, estimated cost and
  duration; a session opens into its calls in order, with a link to the trace in Logfire
  (`trace_url_template`).

The front end of the view is in [frontend](../frontend/README.md); the endpoints are in
[api](../api/docs/endpoints-and-streaming.md#endpoints).

## Switching it off

Set `enabled = false` in `[telemetry]` of `config/settings.toml`.
