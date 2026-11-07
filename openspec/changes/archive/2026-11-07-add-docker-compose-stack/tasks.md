## 1. Configuration and launch

- [x] 1.1 Add `[ui.container]` with `bind_host = "0.0.0.0"` (commented) to `config/settings.toml` and a `container_bind_host` field to `UiSettings` in `config/ui.py`, validated as a loopback or unspecified address; negative tests in `tests/config/` for a public address, an empty string and a non-string.
- [x] 1.2 Add a `--container` flag to `api/__main__.py` (argparse) that binds uvicorn to `container_bind_host`; without it the bind host is `[ui].host` as today. Tests: default binds loopback; the flag binds the container address; the origin guard is built from `[ui].host:[ui].port` in both cases.
- [x] 1.3 Add `api/routers/v1_health.py` (`GET /api/health` -> `{"status": "ok"}`) and register it in `api/main.py`; tests: 200 without any key or keychain, the fake chat model factory is never called, a foreign `Host` is still refused (403).

- [x] 1.4 (Added while applying, user decision 2026-11-07.) `KeyVault` protocol and `EnvironmentVault` in `app/key_vault.py`; `create_app(keys_from_environment=...)` set by `--container`; `get_service_keys` returns environment vaults in that mode; `key_variables()` shared with the lifespan's log protection. Tests: vault reads/blank/unset, save and clear refused with a `.env` message, status and a chat turn use the environment key in container mode, native mode never reads it, the flag reaches `create_app`.

## 2. Image

- [x] 2.1 Add `[[tool.uv.index]]` for the PyTorch CPU wheels (`explicit = true`) and `[tool.uv.sources]` pointing `torch` at it on Linux only; regenerate `uv.lock`; confirm `uv sync` on macOS is unchanged.
- [x] 2.2 Write the multi-stage `Dockerfile` (`frontend`, `deps`, `runtime`, `api` targets; uv and npm cache mounts; `uv sync --frozen --no-dev`; non-root `ecofate` user with fixed UID; `WORKDIR /app`; `HF_HOME` and `.cache` directories owned by that user; `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`; `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`; `HEALTHCHECK` with python `urllib` against `/api/health`; `CMD ["python", "-m", "api", "--container"]`).
- [x] 2.3 Write `.dockerignore` (`.env*` except `.env.example`, `.venv`, `node_modules`, `frontend/dist`, `.cache`, `evals/reports`, `data/raw`, `.git`, `__pycache__`, tool caches, `.logfire`, `.claude`).

## 3. Compose and Makefile

- [x] 3.1 Write `compose.yaml`: `api` built from target `api`, `env_file: .env`, `ports: ["127.0.0.1:8000:8000"]`, volumes `ecofate-cache:/app/.cache` and `hf-cache:/home/ecofate/.cache/huggingface`, `restart: unless-stopped`, health check; declare the named volumes.
- [x] 3.2 Write the `Makefile` with `help` (from `##` comments), `up`, `down`, `build`, `logs`, `shell`, `warm` (downloads the pinned encoder into the volume), `test`, `lint`, `check` (ruff format check, ruff, pyright, bandit, function length, pytest, frontend check), `eval`, `catalogue`, `migrate` (prints that nothing needs migrating yet; filled by `migrate-to-postgresql`).
- [x] 3.3 Add `tests/test_container_files.py`: `.dockerignore` excludes `.env` and keeps `.env.example`; `compose.yaml` publishes the API port only on `127.0.0.1`; no `ENV`/`ARG` line of the `Dockerfile` names a variable ending in `_KEY` or `_TOKEN`; the final stage sets a non-root `USER`; every Makefile target listed in the README exists.

## 4. Documentation

- [x] 4.1 README: "Run with Docker" quick start (`cp .env.example .env`, `docker compose up --build`, open `http://127.0.0.1:8000`), the Makefile target table, the keychain-unavailable note (keys come from `.env` in the container), image size and RAM, `make warm`.
- [x] 4.2 Root `CLAUDE.md`: add `make check` / `docker compose up` to Commands (stay within the line budget of `tests/test_claude_md.py`); `api/CLAUDE.md`: the container bind address comes only from `[ui.container]` through the `--container` flag.

## 5. Verification

- [x] 5.1 `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`, `uv run pyright`, bandit, the function-length check, `npm --prefix frontend run check`, `uv run pre-commit run --all-files` (twice, for the trailing-comma hook).
- [x] 5.2 Live check: `docker compose up --build`; the health check turns healthy; `curl -s http://127.0.0.1:8000/api/health` answers ok; the UI loads; one chat turn with the `.env` OpenAI key completes; a request with `Host: evil.example` answers 403; `docker compose exec api id -u` is not 0; `docker history` shows no key; after `docker compose down && up` the SCC index and model are not rebuilt.
