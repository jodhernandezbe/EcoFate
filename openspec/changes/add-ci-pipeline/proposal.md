## Why

Every quality gate of the project (ruff, strict pyright, bandit, function length,
detect-secrets, pytest, the frontend check) runs only in the local pre-commit hook, so a
reviewer cannot see that they pass and a push from a machine without the hooks is never
checked. The capstone awards 2 points for CI/CD, and the deployment change
(`add-cloud-deployment`) needs a pipeline that builds and publishes the images it deploys.
A CI run on every push and pull request makes the gates visible, repeatable and
independent of one laptop.

## What Changes

- Add a GitHub Actions workflow `.github/workflows/ci.yml`, triggered on pull requests and
  on pushes to `main`, with three jobs:
  - `python`: `uv sync --locked`, then the same checks as `.pre-commit-config.yaml`
    (`pre-commit run --all-files` with the `frontend-check` and `pytest` hooks skipped, so
    they run as their own steps), `uv run pytest -q` (smoke and eval markers excluded, as
    locally), and `uv run pip-audit`.
  - `frontend`: `npm --prefix frontend ci` and `npm --prefix frontend run check`, then
    `npm --prefix frontend run build`.
  - `docker`: builds the `api` and `worker` targets of the `Dockerfile` (from
    `add-docker-compose-stack`) with BuildKit cache, without pushing, and runs a
    `docker compose up --wait` smoke test that calls the API health endpoint.
- Add a manual workflow `.github/workflows/evals.yml` (`workflow_dispatch`, with a choice of
  `scenarios`, `catalogue` or `judge <run-dir>`) that runs the agent evaluations with the
  `OPENAI_API_KEY` repository secret (plus `COMPTOX_API_KEY` and `CENSUS_API_KEY` for the
  catalogue) and uploads `evals/reports/<timestamp>/` as a workflow artifact. It never runs
  on push or pull request, because it costs tokens.
- Caching: uv (`astral-sh/setup-uv` with its cache keyed on `uv.lock`), npm (keyed on
  `frontend/package-lock.json`), pre-commit environments (keyed on
  `.pre-commit-config.yaml`), Docker layers (GitHub Actions cache backend).
- Secret hygiene: workflows declare `permissions: contents: read` by default; secrets are
  passed only as step environment variables to the steps that need them, never echoed;
  third-party actions are pinned to a full commit SHA; pull requests from forks get no
  secrets (the default), so the evals workflow cannot run on them.
- A status badge for `ci.yml` at the top of the README.

## Capabilities

### New Capabilities

- `ci-pipeline`: the continuous-integration workflows (what triggers them, which checks
  they run, how evaluations run on demand, caching and secret handling).

### Modified Capabilities

(none)

## Impact

- New: `.github/workflows/ci.yml`, `.github/workflows/evals.yml`,
  `.github/dependabot.yml` (weekly updates for GitHub Actions, uv and npm).
- `README.md` (badge, a CI paragraph in Development), `.pre-commit-config.yaml` unchanged
  (CI reuses it as the single list of checks).
- No change to Python packages or the frontend source. Requires the repository to be on
  GitHub; the evals workflow needs the `OPENAI_API_KEY` secret set by the owner.
- The publishing of images to GHCR on a tag belongs to `add-cloud-deployment`.
