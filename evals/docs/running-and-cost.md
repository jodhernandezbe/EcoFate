[← Documentation index](../../README.md#documentation) · [Evals](../README.md)

# Running it and its cost

    uv run python -m evals run                     # all unblocked scenarios: PASS/FAIL + reasons
    uv run python -m evals run chemical-name-only  # one scenario
    uv run python -m evals record full-assessment-with-nei-stacks  # re-record from live services
    uv run python -m evals record-extra <scenario> # record only a scenario's extra calls
    uv run python -m evals catalogue               # every catalogue question, live
    uv run python -m evals judge evals/reports/<timestamp>  # LLM-judge that run against its labels.json
    uv run pytest -m eval                          # the scripted scenarios as tests
    make eval / make catalogue                     # the same through the Makefile

All of them need `OPENAI_API_KEY` and cost tokens; recording and the catalogue also need the Census
and CompTox keys for complete answers. They are never part of pre-commit or the default `pytest`
run. In CI they run only by hand: **Actions -> Evaluations -> Run workflow**, choosing `scenarios` or
`catalogue`; reports are attached to the run as an artifact for 30 days. Judging runs locally because
`labels.json` is never in GitHub.

Cost, from `evals/reports/20261102-195041/catalogue.json`: the 50 answers used 2,186,531 tokens and
an estimated USD 2.39 (prices from `[ui.pricing]`, dated 2026-10-20), and took 2,950 s of agent time in
total. The cost of the judge's 50 calls per iteration is not recorded. Unit tests of the harness use a
scripted fake chat model and run in pre-commit (`tests/evals/`).
