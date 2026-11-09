#
# Mission Mars — single runtime container:
#   stage 1 builds the React/Vite frontend,
#   stage 2 runs the FastAPI backend, which also serves the built frontend.
#
# Build context is the repository root (see docker-compose.yml).
# Base images can be overridden, e.g. to use a registry mirror:
#   docker compose build --build-arg PYTHON_IMAGE=... --build-arg NODE_IMAGE=...

ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim

# ---------------------------------------------------------------- frontend
FROM ${NODE_IMAGE} AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY config/ ./config/
COPY --from=frontend /build/dist ./static
# Default location of the verified EVB Lite profile (./config is mounted here).
ENV EVB_PROFILE_PATH=/app/config/evb_profile.json

# Run as an unprivileged user. /data is the persistent volume.
RUN useradd --system --uid 1000 --create-home mission \
    && mkdir -p /data \
    && chown -R mission:mission /data
USER mission

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# One worker: sensor acquisition and capture state live in this process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
