## Why

Running EcoFate today means installing uv, Node and the Python toolchain, building the
frontend, and then running two commands; a peer reviewer who only wants to see the app has to
reproduce the whole developer setup. The capstone rewards containerised dependencies (+1), a
`docker compose up` that starts the whole system (+2) and a Makefile (+1), and every later
step of the roadmap (PostgreSQL, Redis, the Celery worker, the AWS deployment) adds a service
that needs a place to live. This change creates that place: one image, one compose file, one
Makefile.

## What Changes

- A multi-stage `Dockerfile`: a Node stage builds `frontend/dist`; a uv stage installs the
  locked Python dependencies (no dev group) into a virtual environment; a slim runtime stage
  copies the venv, the source packages, `config/`, `prompts/`, `data/` and the built
  frontend, runs as a non-root user, and starts the web program. Named targets (`api` now,
  `worker` later) share the same layers.
- PyTorch is installed from the CPU-only wheel index on Linux, so the image does not carry
  the CUDA libraries (several GB) that the read-across encoder never uses.
- A `.dockerignore` that keeps secrets (`.env*`), caches, `node_modules`, `.venv`,
  `evals/reports/`, `data/raw/` and git metadata out of the build context.
- A `compose.yaml` with the `api` service: port published on the host's loopback only
  (`127.0.0.1:8000:8000`), `.env` passed as the environment, named volumes for `.cache/`
  (SCC index, PubChem answers) and the Hugging Face cache (the 500 MB MolDeBERTa model is
  downloaded once and kept), a health check, and `restart: unless-stopped`.
- A liveness endpoint `GET /api/health` that answers without running the agent or reading
  any key, used by the container health check.
- A `--container` flag for `python -m api`: the server then listens on the bind address in
  `[ui.container]` (`0.0.0.0`, reachable only through the published loopback port). Without
  the flag nothing changes; the host and origin checks still use the configured `[ui]` host
  and port, so a browser at `http://127.0.0.1:8000` is accepted and other hosts are refused.
- Inside the container no OS keychain exists, so the keyring backend is set explicitly to the
  failing backend: the settings dialog reports the keychain as unavailable, and the keys come
  from `.env` (the existing environment fallback). Per-user key storage arrives with
  `add-byok-key-isolation`.
- A `Makefile` with `help`, `up`, `down`, `build`, `logs`, `shell`, `test`, `lint`, `check`
  (everything pre-commit runs), `eval`, `catalogue` and `migrate` (a no-op placeholder that
  `migrate-to-postgresql` fills in).
- README: a "Run with Docker" quick start ahead of the uv instructions.

## Capabilities

### New Capabilities

- `container-runtime`: the image, the compose stack, the health endpoint, the keychain
  behaviour inside the container, and the Makefile.

### Modified Capabilities

- `web-ui-server`: the launch command gains the container bind mode; the host and origin
  checks are stated against the configured public host and port rather than the bind address.
- `app-configuration`: a `[ui.container]` table with the container bind address.
- `api-key-vault`: in container mode the web program reads each key from its environment
  variable (no credential store exists there); native behaviour is unchanged.

## Impact

- New files: `Dockerfile`, `.dockerignore`, `compose.yaml`, `Makefile`,
  `api/routers/v1_health.py`.
- Changed: `api/__main__.py` (flag), `api/main.py` (router), `config/ui.py` +
  `config/settings.toml` (`[ui.container]`), `pyproject.toml` (`[tool.uv.sources]` for the
  CPU torch index on Linux; `uv.lock` regenerated), `.env.example`, README, root `CLAUDE.md`
  (commands), `api/CLAUDE.md`.
- No change to `agent/`, `tools/`, `models/` or `evals/`. The native `uv run python -m api`
  path keeps working exactly as before.
- Image size is dominated by torch (CPU) and RDKit; expect about 2 GB. The host needs about
  4 GB of RAM once the read-across encoder is loaded.
