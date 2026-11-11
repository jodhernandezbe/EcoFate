# syntax=docker/dockerfile:1.7
# EcoFate image. Targets: `api` (web program) and `worker` (the background agent worker), both on
# `runtime`, so the two run exactly the same code.
# Secrets never enter the image: they reach the container at run time from `.env` (compose).

# --- frontend: build the React app into frontend/dist -------------------------------------
FROM node:24-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- deps: the locked Python dependencies (no dev group) in /app/.venv ------------------------
FROM python:3.13-slim-bookworm AS deps
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --- runtime: venv + source + data + built frontend, non-root -----------------------------
FROM python:3.13-slim-bookworm AS runtime
ARG APP_UID=10001
RUN groupadd --system --gid ${APP_UID} ecofate \
    && useradd --system --uid ${APP_UID} --gid ecofate --create-home --home-dir /home/ecofate ecofate
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/ecofate/.cache/huggingface \
    PYTHON_KEYRING_BACKEND=keyring.backends.fail.Keyring
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY pyproject.toml LICENSE NOTICE ./
COPY agent/ agent/
COPY api/ api/
COPY app/ app/
COPY commons/ commons/
COPY config/ config/
COPY models/ models/
COPY prompts/ prompts/
COPY storage/ storage/
COPY alembic.ini ./
COPY tools/ tools/
COPY worker/ worker/
COPY data/ data/
COPY --from=frontend /src/frontend/dist frontend/dist
# Run-time caches (SCC index, PubChem answers, the Hugging Face model) live in volumes mounted
# here; create them owned by the app user so a fresh named volume inherits that ownership.
RUN mkdir -p /app/.cache "${HF_HOME}" \
    && chown -R ecofate:ecofate /app/.cache /home/ecofate/.cache
USER ecofate

# --- api: the web program ------------------------------------------------------------------
FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "api", "--container"]

# --- worker: the background agent worker (runs the chat turns the API queues) -----------------
# Queue, concurrency, prefetch and time limits come from [worker] in config/settings.toml.
FROM runtime AS worker
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["sh", "-c", "celery -A worker.celery_app inspect ping --timeout 5 -d celery@$(hostname) > /dev/null"]
CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=INFO", "--without-gossip", "--without-mingle"]
