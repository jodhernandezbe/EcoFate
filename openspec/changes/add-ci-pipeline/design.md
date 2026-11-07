## Context

See proposal.md for motivation. What shapes the approach:

- `.pre-commit-config.yaml` is already the single list of gates: file hygiene,
  add-trailing-comma, ruff (lint + format), `uv-lock`, detect-secrets against
  `.secrets.baseline`, and local hooks for function length, strict pyright, bandit, the
  frontend check and pytest. The local hooks run through `uv run` and `npm`, so they need the
  project environment and `node_modules` installed.
- pytest markers in `pyproject.toml`: `smoke`, `comptox`, `census`, `logfire` (live
  services, skipped without keys) and `eval` (real chat model). The default `pytest` run
  excludes `eval`; smoke tests skip themselves without keys, so CI needs no secret for the
  default run.
- `frontend/package.json` `check` = contract check + `tsc` + eslint + vitest; `build` =
  `tsc -b && vite build`.
- Evaluation commands: `uv run pytest -m eval`, `uv run python -m evals run`,
  `... catalogue`, `... judge <run-dir>`; reports land in `evals/reports/<timestamp>/`.
- The repository has no `.github/` folder today.
- `add-docker-compose-stack` (ROADMAP step 1) provides the `Dockerfile` with `api` and
  `worker` targets and `compose.yaml`; this change only builds them.

## Goals / Non-Goals

**Goals:**
- Every push and pull request runs the same gates as pre-commit, plus the frontend build and
  the container build, and shows the result on the commit.
- Evaluations can be run from GitHub on demand, with their reports downloadable.
- No secret is needed for the default CI run, and none can leak into a log.

**Non-Goals:**
- Publishing images or deploying (that is `add-cloud-deployment`).
- Running evaluations automatically on every change (token cost, nondeterminism).
- Branch protection settings (a repository setting the owner turns on; documented).

## Decisions

1. **Reuse pre-commit as the check list.** CI runs `uv run pre-commit run --all-files
   --show-diff-on-failure` with `SKIP=frontend-check,pytest`, then runs those two as named
   steps so their output is readable. Alternative: re-list every tool in YAML; rejected
   because the two lists would drift.
2. **Three parallel jobs** (`python`, `frontend`, `docker`) instead of one: faster feedback
   and a failing area is obvious from the job name. The `python` job also installs Node,
   because no hook needs it once `frontend-check` is skipped there.
3. **uv from `astral-sh/setup-uv`** with `enable-cache: true` and the Python version from
   `.python-version`; `uv sync --locked` fails if `uv.lock` is stale, matching the `uv-lock`
   hook.
4. **Docker smoke test**: `docker compose up --wait` against `compose.yaml` with a CI env
   file holding throwaway values (no real keys), then `curl --fail` on the health endpoint,
   then `docker compose down -v`. Alternative: build only; rejected because it does not
   prove the stack starts (the "docker compose up starts everything" criterion).
5. **Evals are `workflow_dispatch` only**, inputs validated by a `choice` input and a
   run-directory pattern (`^[0-9]{8}-[0-9]{6}$`), passed through an environment variable,
   never interpolated into a shell line (prevents script injection). The step uses the
   `OPENAI_API_KEY` secret and a GitHub `environment: evals` so the owner can require
   approval.
6. **Pinned actions and least privilege**: `permissions: contents: read` at workflow level,
   each third-party action pinned to a full SHA with the tag in a comment, Dependabot keeps
   them current. `concurrency` cancels superseded runs of the same branch.

## Risks / Trade-offs

- [Read-across model download in tests] → tests already use fakes for the MolDeBERTa model;
  if any test downloads it, CI is slow. Mitigation: cache `~/.cache/huggingface` keyed on
  the pinned revision in `[read_across.model]`.
- [Detect-secrets false positive on CI-only files] → the baseline is updated in the same
  change after review, as the README describes.
- [Flaky live smoke tests] → they skip without keys and CI sets none.
- [Docker build time] → GitHub Actions cache backend for BuildKit layers; the frontend stage
  caches `node_modules` by lockfile.

## Migration Plan

Add the workflows on a branch, open a pull request, confirm all three jobs pass, merge.
Then the owner turns on branch protection for `main` requiring the three checks.
Rollback: delete the workflow files; nothing else depends on them.
