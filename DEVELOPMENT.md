[← Documentation index](README.md#documentation) · [Getting started](docs/getting-started.md) · [Architecture](docs/architecture.md)

# Development

What to know before changing EcoFate.

- [Set up](#set-up)
- [Before every commit](#before-every-commit)
- [Tests](#tests)
- [Rules the checks enforce](#rules-the-checks-enforce)
- [Where things go](#where-things-go)
- [Things that are easy to get wrong](#things-that-are-easy-to-get-wrong)
- [Continuous integration](#continuous-integration)
- [Releasing](#releasing)

## Set up

    uv sync                        # Python 3.13 dependencies
    npm --prefix frontend ci       # frontend dependencies
    uv run pre-commit install      # once: enable the git hooks
    cp .env.example .env           # then fill it in (docs/getting-started.md)

`make help` lists the everyday commands; `make db` and `make redis` start PostgreSQL and Redis
for native runs.

## Before every commit

    uv run ruff format .
    uv run pre-commit run --all-files

Pre-commit is the gate, and CI runs the same hooks: file hygiene, ruff (lint and format), the
`uv lock` check, detect-secrets, strict pyright, bandit, the function-length check, pytest and the
frontend check (contract diff, tsc, eslint, vitest). Never bypass it with `--no-verify`. `make
check` runs the same set by hand; `make audit` checks dependency CVEs.

## Tests

| Command | What it runs |
|---|---|
| `uv run pytest` | the default suite: no network, no keys, no database |
| `make test-db` | tests against a real PostgreSQL (`postgres` marker) |
| `make test-redis` | tests against a real Redis (`redis` marker) |
| `uv run pytest -m smoke` | live checks against the real data services (some need the CompTox, Census or Logfire key) |
| `uv run pytest -m eval` | agent evaluations with a real chat model (OpenAI key, costs tokens) |
| `npm --prefix frontend run check` | frontend contract, types, lint and unit tests |
| `npm --prefix frontend run test:visual` | screenshot tests in Chromium, light and dark |

`tests/` mirrors the package layout, and every test directory needs an `__init__.py`. Give each
rule a negative test. Never invent numbers in tests or stubs that look like real data.

## Rules the checks enforce

- **Types:** strict pyright; annotate every function, no untyped `dict`, no `Any` unless
  unavoidable. Every Python file starts with `from __future__ import annotations`.
- **Function length:** at most 18 body lines in the source packages; split long functions into
  named helpers instead of raising the limit.
- **Layering:** imports follow one direction (`tests/test_layering.py`); the allowed directions
  are in [Architecture](docs/architecture.md#package-layers).
- **Secrets:** none in code, images or docs; detect-secrets guards `.secrets.baseline`.
- **Docs:** every relative link and heading anchor in the READMEs and `docs/` must exist
  (`tests/test_docs_links.py`); the root `CLAUDE.md` stays within 80 lines.
- **Frontend:** `src/types/api.ts` is generated from the API schema (`npm run gen:types`), never
  edited by hand; components use the design tokens, never literal colours.

## Where things go

| Change | Where |
|---|---|
| A URL, endpoint, unit, threshold, timing or model name | `config/settings.toml` with a typed loader ([config/](config/README.md)); never hard-coded in Python |
| An equation | `models/`, pure NumPy, units in the docstring ([models/](models/README.md)) |
| A new tool | its folder under `tools/`, the folder's `TOOLS` list, `tools/registry.py` and the registry test ([tools/](tools/README.md#adding-a-tool)) |
| What the model is told | the tool's docstring for when to use it and how to read its output; `prompts/` for how an assessor reasons ([prompts/](prompts/README.md)) |
| A different LLM provider | `[agent]` in the settings and `app/chat_model.py` ([agent/](agent/README.md#swapping-the-llm-provider)) |
| A database table or column | `storage/` with an Alembic migration that only adds within a release ([storage/](storage/README.md)) |
| Something users see | `frontend/`, following `frontend/DESIGN.md` ([frontend/](frontend/README.md)) |

Each folder also has a `CLAUDE.md` with the rules coding agents follow there; they apply to
people too.

## Things that are easy to get wrong

- **Prompt and tool-docstring edits change the agent's behaviour.** Re-run the evaluations
  before keeping one ([evals/](evals/README.md)); a wording change can make the model recall a
  CAS number from memory, which the rules forbid.
- **Mocks can repeat your own mistake.** After changing how a tool reads an external service,
  make one live call (`pytest -m smoke`) before calling it done.
- **External data is untrusted.** Validate it once at the boundary; a missing or implausible
  value becomes absent with a reason, never a guess ([design principles](docs/design-principles.md)).
- **The UI shows only what the API sent.** It never computes, converts or rounds a scientific
  value; an absent value reads "not reported".
- **Docker keeps old containers.** After a code change run
  `docker compose up -d --build --force-recreate api worker`.
- **Diagrams follow the code.** The `.drawio.svg` files in `docs/diagrams/` name real modules,
  services and graph nodes; update the diagram in the same change that renames one.

## Continuous integration

GitHub Actions runs `.github/workflows/ci.yml` on every pull request and push to `main` in three
jobs: `python` (the pre-commit hooks, pytest, `make audit`), `frontend` (`npm ci`, check, build)
and `docker` (builds both images, starts the stack with placeholder secrets, calls
`/api/health`). It needs no secret and never runs the token-costing evaluations, which run by hand
(**Actions → Evaluations → Run workflow**). Actions are pinned to commit SHAs and Dependabot
proposes updates weekly.

## Releasing

Bump `version` in `pyproject.toml` and `CITATION.cff` (with `date-released`), merge through a
pull request with CI green, then tag `v<version>` on `main`. The tag builds the images and, after
the owner's approval, deploys to production with an automatic rollback if the health check fails
([deploy/](deploy/README.md)). Publishing a GitHub release archives it on Zenodo
([License and citation](docs/citation.md)).
