## Context

See proposal.md for motivation and `openspec/ROADMAP.md` for the target topology (this
change introduces the `api` service; `db`, `mailpit`, `redis`, `worker` and `caddy` come in
later changes). What shapes the approach:

- `api/__main__.py` loads `.env`, configures telemetry, checks `frontend/dist/index.html`
  and runs uvicorn on `[ui].host`/`[ui].port`. `config/ui.py` refuses a non-loopback host.
  `api/core/origin_guard.py` compares every request's `Host` with the configured origin
  (`http://{host}:{port}`) and state-changing requests' `Origin` with it.
- All paths in `config/settings.toml` are relative to the working directory (`data/...`,
  `.cache/scc_index`, `.cache/pubchem/responses.sqlite`, `frontend/dist`), so the image's
  working directory must be the project root.
- `data/` is committed and small enough to bake in (NEI shards about 1.4 MB, TRI parquet
  shards, the census baseline). `.cache/` is built at run time (SCC index on first use,
  PubChem answers), so it needs a volume to survive restarts.
- The read-across encoder (`SaeedLab/MolDeBERTa-base-123M-mtr`, pinned revision in
  `[read_across.model]`) is downloaded from Hugging Face on first use, about 500 MB, into the
  Hugging Face cache (`HF_HOME`).
- `uv.lock` resolves `torch` from PyPI; on Linux x86_64 that pulls the CUDA libraries
  (several GB) although the encoder runs on CPU.
- `app/key_vault.py` uses `keyring`; a slim Linux container has no Secret Service, so
  `keyring` would pick an unpredictable backend or fail late. Every key already falls back to
  its environment variable (`OPENAI_API_KEY`, `CENSUS_API_KEY`, `COMPTOX_API_KEY`).
- No health endpoint exists today.

## Goals / Non-Goals

**Goals:**
- `git clone && cp .env.example .env && docker compose up` serves the working app at
  `http://127.0.0.1:8000`, with no local Python or Node.
- The container keeps every security property of the native run: reachable only from the
  host's loopback, same Host/Origin checks, no key in the image, the logs or a layer.
- A Makefile that is the one place a reviewer looks for "how do I run X".

**Non-Goals:**
- PostgreSQL, Redis, the worker, TLS and the production override (later changes).
- Per-user key storage (`add-byok-key-isolation`); the container uses `.env` keys.
- Running the test suite inside the image (the runtime image has no dev group; `make test`
  runs on the host through uv, and CI runs it on a runner).
- GPU support.

## Decisions

1. **One multi-stage Dockerfile with named targets.** Stages: `frontend` (`node:22-slim`,
   `npm ci && npm run build`), `deps` (`ghcr.io/astral-sh/uv` copied into
   `python:3.13-slim-bookworm`, `uv sync --frozen --no-dev --no-install-project` with a cache
   mount, so source edits do not reinstall dependencies), `runtime` (slim base, venv and
   source copied, `USER ecofate` with a fixed UID, `WORKDIR /app`), and `api` (`CMD ["python",
   "-m", "api", "--container"]`). The worker of change 7 becomes another target on
   `runtime`. Alternative: separate Dockerfiles per service; rejected, they would drift.
2. **CPU torch through uv sources.** `[tool.uv.sources] torch = [{ index = "pytorch-cpu",
   marker = "sys_platform == 'linux'" }]` with an explicit `[[tool.uv.index]]`
   (`https://download.pytorch.org/whl/cpu`, `explicit = true`). macOS keeps the PyPI wheel.
   Alternative: a separate requirements file for the image; rejected, it would bypass the
   lock file that pre-commit checks.
3. **Bind address from configuration, chosen by a flag.** `[ui.container].bind_host =
   "0.0.0.0"` is validated as either a loopback address or the unspecified address, and is
   used only when `python -m api --container` runs. `[ui].host` and `[ui].port` remain the
   public origin that the origin guard checks, so the guard is unchanged. Compose publishes
   `127.0.0.1:8000:8000`, so the port is not reachable from the network. Alternatives: an
   environment variable for the host (rejected: `api/CLAUDE.md` forbids reading hosts from the
   environment); a second settings file for containers (rejected: a full copy that drifts).
4. **Keychain explicitly off in the container; keys from the environment.** The image sets
   `PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring`. Found while applying: the web
   program, unlike the CLI, had no environment fallback (the `api-key-vault` spec reads keys
   only from the credential store), so every container turn failed with "keychain
   unavailable", and the chat box stayed disabled because the key status read "not set". Fix
   (user decision, 2026-11-07): with `--container`, `create_app(keys_from_environment=True)`
   makes `get_service_keys` return `EnvironmentVault`s (`app/key_vault.py`, same `KeyVault`
   protocol as `KeyringVault`) reading `[agent].api_key_env_var`, `[population]` and
   `[comptox]` variables. Status reports the variable; save and clear answer 503 naming `.env`.
   Native launches are unchanged (keychain only). Alternatives: fallback everywhere
   (rejected: changes native behaviour); no chat in Docker until BYOK (rejected: breaks the
   compose scenario); `keyrings.alt` file backend (rejected: writes keys to a volume, which
   the key-vault spec forbids). `add-byok-key-isolation` replaces this with per-user keys.
5. **Volumes for what is built at run time.** `ecofate-cache` at `/app/.cache` and `hf-cache`
   at `/home/ecofate/.cache/huggingface` (`HF_HOME`). Both are owned by the non-root user
   (created in the image before `USER`). Alternative: bake the model into the image;
   rejected for now (+500 MB per image push); `make warm` downloads it into the volume once.
6. **Liveness endpoint.** `GET /api/health` returns `{"status": "ok"}` with no agent,
   key, keychain or network access; it passes the origin guard as a safe method. The compose
   health check calls it with Python's `urllib` (no `curl` in the slim image).
   `migrate-to-postgresql` adds a database probe to it.
7. **Secrets only at run time.** `.env` is passed with `env_file`, never copied (it is in
   `.dockerignore`, and a test checks that). No `ARG` or `ENV` carries a key.
8. **Makefile as a thin index.** Every target is one or two commands that already exist
   (`uv run ...`, `docker compose ...`, `npm --prefix frontend ...`); `make help` lists them
   from `##` comments. No logic lives in the Makefile.

## Risks / Trade-offs

- [Image size ~2 GB, first `docker compose build` takes minutes] -> layer order puts
  dependencies before source; BuildKit cache mounts for uv and npm.
- [First read-across call downloads 500 MB inside the container] -> `make warm` and a README
  note; the tool already reports a failed download as a warning, not a crash.
- [Changing the torch source changes `uv.lock`] -> the lock is regenerated and committed in
  this change; pre-commit's `uv lock --check` guards it.
- [`0.0.0.0` inside the container] -> only with the flag, only in compose, and the port is
  published on loopback; the Host check still rejects any other host name.
- [Keychain unavailable in the container confuses users] -> the settings dialog already
  shows the fixed message; the README's Docker section explains `.env`.

## Migration Plan

Additive: native runs are unchanged. Rollback is deleting the new files and reverting
`pyproject.toml`/`uv.lock`.

## Open Questions

None.
