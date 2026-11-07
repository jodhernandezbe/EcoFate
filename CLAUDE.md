# EcoFate

LangChain/LangGraph agent that produces screening-level chemical exposure and risk
assessments. Python 3.13, managed with uv.

## Commands

    uv sync                # install deps
    uv run pytest          # tests
    uv run ruff format .   # format (run before every commit)
    uv run ruff check .    # lint
    uv run pyright         # strict type check
    uv run bandit -c pyproject.toml -r agent app api commons config evals models prompts tools   # security lint
    uv run python scripts/check_function_length.py --max 18 $(git ls-files 'agent/*.py' 'app/*.py' 'api/*.py' 'commons/*.py' 'config/*.py' 'evals/*.py' 'models/*.py' 'prompts/*.py' 'tools/*.py')   # function length
    uv run pytest -m eval  # agent evaluations (OpenAI key, costs tokens; not in pre-commit)
    npm --prefix frontend run check   # frontend (after `npm --prefix frontend ci`); `run build` then `uv run python -m api` serves the UI
    make check / docker compose up    # all of the above at once / the containerised app (`make help`)

Test, format, lint, pyright, bandit, function length and the frontend check must pass before work is
done; pre-commit enforces them (`uv run pre-commit run --all-files`). Never bypass with `--no-verify`;
never put secrets in code or images (detect-secrets guards `.secrets.baseline`).

## Layout and boundaries

- `models/`  pure deterministic NumPy equations; physical units in every docstring.
- `agent/`   orchestration only: graph wiring, state, model calls.
- `tools/`   tool logic only, grouped by concern (`informatics/`, `emissions/`,
  `exposure/`). One module per tool (or small family of tools); its helpers go in a
  same-named subfolder of `helpers/`.
- `prompts/` Markdown prompt files plus `registry.py` to load them.
- `config/`  `settings.toml` plus typed loaders, one module per concern (`loader.py`,
  `stack.py`, `retrieval.py`; shared validators in `parsing.py`) for URLs, endpoints, timing,
  data paths, columns, units and model names. Never hard-code these in Python; add them here.
- `commons/` small, generic, pure utilities used across layers (e.g. `units.py`, Pint-based
  unit conversion). No project knowledge, no I/O, no config reads: callers pass in what they need.
- `app/`     the program: builds the `[agent]` chat model (only here), key vault, runs the agent.
  `api/` is the local web backend (FastAPI, SSE); `frontend/` the React app (only `/api`).
- `evals/`   agent evaluation (outer edge): real chat model, recorded tool outputs, Evidently.
- `tests/`   pytest suite mirroring the package layout (`tests/tools/emissions/test_stack.py` tests `tools/emissions/stack.py`). Every test directory needs an `__init__.py`.

Dependency direction: `agent` -> `tools` -> `models`; `agent` -> `prompts`;
`agent`/`tools`/`models` -> `commons`; `agent`/`tools` -> `config`; `app` -> `agent`/`config`/`tools.credentials`; `evals` -> `app`/`agent`/`tools`/`config`/`prompts`. `api` -> `app`/`agent`/`config`/`prompts`/`commons`/`tools.schemas`/`tools.user_values`; `frontend` -> `api` (HTTP only).
`commons` and `config` import nothing from the project; nothing imports `evals` or `api`.

## Folder-specific rules

Each layer keeps its own rules in a `CLAUDE.md` inside its folder. Claude Code loads these
automatically when working in that folder, so read and follow the one that applies before
editing there:

- `agent/CLAUDE.md`   provider-agnostic orchestration only.
- `commons/CLAUDE.md` generic pure utilities with no project imports.
- `models/CLAUDE.md`  pure deterministic equations with units in every docstring.
- `tools/emissions/rag/CLAUDE.md` SCC retrieval (RAG); the one place a provider is imported.
- `prompts/CLAUDE.md` prompt files, XML structure, loading through the registry.
- `tools/CLAUDE.md`   `@tool` conventions, registry and test requirements.
- `app/CLAUDE.md`     the program and the one chat model factory.
- `evals/CLAUDE.md`   agent evaluation harness, cassettes and scenarios.
- `api/CLAUDE.md`, `frontend/CLAUDE.md` web backend (contract, keys, redaction) and browser app.

A new layer with rules of its own gets a `CLAUDE.md` in its folder, listed here. Keep this file
under 80 lines (`tests/test_claude_md.py`); put detail in folder `CLAUDE.md` files or `docs/`.

## Design principles

SOLID, DRY and defensive programming apply to all code; the full rules are imported here:

@docs/design-principles.md

## Code style

- Every Python file starts (after the docstring) with `from __future__ import annotations`.
- Functions stay short: at most 18 body lines (signature, docstring, blank lines and comments
  not counted; nested functions count toward the outer one). Split long ones into small named
  helpers. Enforced by `scripts/check_function_length.py` as a pre-commit hook on the source
  packages (not `tests/`); never raise the limit or skip the hook to make code fit.
- Strict static typing: annotate all functions; no untyped `dict`, no `Any` unless unavoidable.
- Formatting and linting are enforced by ruff (config in `pyproject.toml`) and a hook that
  adds trailing commas to multi-line constructs; do not hand-format or add `# noqa` unjustified.
- Never invent numeric values in tool stubs or tests that look like real data.
