## 1. CI workflow

- [ ] 1.1 Write `.github/workflows/ci.yml`: triggers on `pull_request` and `push` to `main`; `permissions: contents: read`; `concurrency` group per ref with cancel-in-progress; every third-party action pinned to a full commit SHA.
- [ ] 1.2 `python` job: checkout, `astral-sh/setup-uv` (cache on `uv.lock`, Python from `.python-version`), `uv sync --locked`, cache `~/.cache/pre-commit` on `.pre-commit-config.yaml`, `SKIP=frontend-check,pytest uv run pre-commit run --all-files --show-diff-on-failure`, `uv run pytest -q`, `uv run pip-audit`.
- [ ] 1.3 `frontend` job: `actions/setup-node` (version from `frontend/package.json` engines or `.nvmrc`, npm cache on `frontend/package-lock.json`), `npm --prefix frontend ci`, `npm --prefix frontend run check`, `npm --prefix frontend run build`.
- [ ] 1.4 `docker` job: `docker/setup-buildx-action`, build targets `api` and `worker` with `cache-from/cache-to: type=gha`, `docker compose --env-file .github/ci.env up --wait`, `curl --fail` the health endpoint, `docker compose down -v` in an `always()` step; `.github/ci.env` holds placeholder values only and is allow-listed in `.secrets.baseline` after review.

## 2. Evaluations on demand

- [ ] 2.1 Write `.github/workflows/evals.yml`: `workflow_dispatch` with a `choice` input (`scenarios`, `catalogue`, `judge`) and a `run_dir` string input; `environment: evals`; inputs reach the shell only through `env:` and `run_dir` is checked against `^[0-9]{8}-[0-9]{6}$` before use.
- [ ] 2.2 Map each choice to its command (`uv run python -m evals run`, `... catalogue`, `... judge evals/reports/$RUN_DIR`), with `OPENAI_API_KEY` (and `COMPTOX_API_KEY`, `CENSUS_API_KEY` for `catalogue`) from repository secrets as step env only; upload `evals/reports/` with `actions/upload-artifact` (retention 30 days) even when the run fails.

## 3. Maintenance

- [ ] 3.1 Add `.github/dependabot.yml` (weekly: `github-actions`, `uv` at `/`, `npm` at `/frontend`).

## 4. Documentation

- [ ] 4.1 README: CI badge under the title; a "Continuous integration" paragraph in Development (what runs on every push, how to start the evals workflow, which secrets the owner sets, recommendation to require the three checks on `main`).

## 5. Verification

- [ ] 5.1 `actionlint` (via `uvx` or the Docker image) passes on both workflows; `uv run pre-commit run --all-files` passes (check-yaml covers the new files).
- [ ] 5.2 Push a branch and confirm the three CI jobs pass on GitHub; confirm a deliberately failing ruff error fails the `python` job, then revert it.
- [ ] 5.3 Start the evals workflow once with `scenarios` (owner approves the token cost) and confirm the report artifact downloads and that no secret value appears in the log.
