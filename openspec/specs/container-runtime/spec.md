# container-runtime Specification

## Purpose

Runs the whole application from one image with `docker compose up`: a multi-stage image built
from the repository with no secret in it, a compose stack reachable only from the host's
loopback, a liveness endpoint for the health check, keys from the environment where no OS
keychain exists, and a Makefile that indexes the everyday commands.

## Requirements

### Requirement: One image built from the repository
The repository SHALL contain a multi-stage `Dockerfile` that builds the frontend and installs
the locked Python dependencies (without the development group) in build stages, and produces
a runtime image holding the virtual environment, the source packages, `config/`, `prompts/`,
`data/` and the built frontend, with the project root as its working directory. The runtime
image SHALL run as a non-root user. On Linux, PyTorch SHALL come from the CPU-only wheel
index declared in `pyproject.toml`, so the image carries no CUDA libraries.

#### Scenario: Build
- **WHEN** `docker compose build` runs on a clean checkout
- **THEN** the image builds from `uv.lock` and `frontend/package-lock.json` without network access to anything but the package indexes, and contains `frontend/dist/index.html`

#### Scenario: Non-root user
- **WHEN** a process starts in the runtime image
- **THEN** its user id is not 0

#### Scenario: Lock file unchanged by the build
- **WHEN** the image installs dependencies
- **THEN** it uses the frozen lock file and fails if `uv.lock` does not match `pyproject.toml`

### Requirement: No secret in the image or build context
The build context SHALL exclude `.env` files (except `.env.example`), virtual environments,
caches, `node_modules`, evaluation reports, raw downloads and git metadata. No `Dockerfile`
instruction SHALL set or pass an API key, token or password; secrets SHALL reach the container
only at run time through the environment.

#### Scenario: .env excluded
- **WHEN** the build context is assembled with a `.env` file present
- **THEN** `.env` is not in the context and `.env.example` is

#### Scenario: No key in a layer
- **WHEN** the `Dockerfile` is checked
- **THEN** no `ENV` or `ARG` instruction names a variable ending in `_KEY`, `_TOKEN` or `_PASSWORD`

### Requirement: Compose starts the application
`docker compose up` SHALL start the web program from the image with the variables of `.env`,
publish its port on the host's loopback interface only, keep the run-time caches (`.cache/`
and the Hugging Face model cache) in named volumes, restart it unless stopped, and report it
healthy only when its health endpoint answers.

#### Scenario: Whole system with one command
- **WHEN** a reviewer copies `.env.example` to `.env`, adds an OpenAI key and runs `docker compose up`
- **THEN** the interface is served at `http://127.0.0.1:8000` and a chat turn completes

#### Scenario: Port not exposed to the network
- **WHEN** the compose file is checked
- **THEN** the API port is published as `127.0.0.1:<port>:<port>`, never on all interfaces

#### Scenario: Caches survive a restart
- **WHEN** the stack is stopped and started again
- **THEN** the SCC index and the downloaded encoder are reused, not rebuilt

### Requirement: Health endpoint
`GET /api/health` SHALL answer 200 with `{"status": "ok"}` while the web program is serving,
without running the agent, reading any key or the keychain, or calling an external service.
It SHALL be subject to the same Host check as every other endpoint.

#### Scenario: Healthy
- **WHEN** the health endpoint is called with the configured host
- **THEN** it answers 200 with `{"status": "ok"}` and no chat model is built

#### Scenario: Foreign host
- **WHEN** the health endpoint is called with another `Host` header
- **THEN** it answers 403

### Requirement: No keychain inside the container
The image SHALL select the failing keyring backend explicitly, and the web program launched
with the container flag SHALL read every key (OpenAI, Census, CompTox) from its configured
environment variable instead of the credential store. Saving or clearing a key in that mode
SHALL fail with a user-safe message saying the keys come from the `.env` file, and no key SHALL
be written to a file, volume or the environment. Key statuses SHALL report whether each
variable holds a key, never any part of it. Without the container flag the web program SHALL
NOT read keys from the environment.

#### Scenario: Saving a key in the container
- **WHEN** a user saves or clears the OpenAI key in the settings dialog of the containerised app
- **THEN** the response is 503 with a message naming the `.env` file, and nothing is written

#### Scenario: Keys from .env
- **WHEN** `.env` sets `OPENAI_API_KEY` and a chat turn runs in the container
- **THEN** the turn uses that key and the OpenAI key status reports it as configured

#### Scenario: Native launch ignores the environment
- **WHEN** the web program runs without the container flag, the environment variable is set and the credential store holds no key
- **THEN** a chat turn ends with the add-your-key message and the environment key is not used

### Requirement: Makefile entry points
The repository SHALL contain a `Makefile` whose targets wrap existing commands: `help` (lists
every target with its description), `up`, `down`, `build`, `logs`, `shell`, `warm`, `test`,
`lint`, `check`, `eval`, `catalogue` and `migrate`. A target SHALL hold no logic beyond the
commands it runs.

#### Scenario: Help
- **WHEN** `make help` runs
- **THEN** every target is listed with a one-line description

#### Scenario: Check matches pre-commit
- **WHEN** `make check` runs
- **THEN** it runs the format check, lint, type check, security lint, function-length check, tests and frontend check, and fails if any fails
