# NexAgent Backend — multi-stage Dockerfile
#
# Stages:
#   dev   — development image (lightweight, deps installed at runtime via pip)
#   prod  — production image (all deps baked in, multi-worker)
#
# Build:
#   docker compose up -d          (uses dev target, code mounted as volume)
#   docker compose build gateway  (explicit rebuild)

# ── Base ──────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONPATH="/app/backend/packages/core:/app/backend" \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1


# ── Dev stage ─────────────────────────────────────────────────────────────────
# Code is mounted as a volume at runtime so edits are reflected without rebuild.
# Only the packages that are slow to install are pre-baked here.
FROM base AS dev

# Pre-install heavy packages so container starts fast even on first run
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --retries 10 --timeout 60 \
    "langchain>=1.2.0" \
    "langchain-openai>=1.1.0" \
    "langchain-community>=0.3.0" \
    "langgraph>=1.0.6" \
    "langgraph-checkpoint-sqlite>=3.0.0" \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.34.0" \
    "python-dotenv>=1.1.0" \
    "pydantic>=2.10.0" \
    "pyyaml>=6.0.0" \
    "httpx>=0.28.0" \
    "tiktoken>=0.8.0" \
    "asyncpg>=0.30.0" \
    "sse-starlette>=2.1.0" \
    "python-multipart>=0.0.26" \
    "pymilvus>=2.6,<2.7" \
    "neo4j>=5.0.0" \
    "lightrag-hku>=1.3.0" \
    "pypdf>=4.0.0" \
    "python-docx>=1.1.0" \
    "python-pptx>=1.0.0" \
    "markdownify>=0.13.0"

# The gateway command (in docker-compose.yml) runs:
#   pip install -e /app/backend/packages/core && uvicorn --reload
# so nexagent-core is installed in editable mode from the mounted volume.

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8001/health/ready || exit 1


# ── Prod stage ────────────────────────────────────────────────────────────────
# All code baked in, optimized for production deployment.
FROM base AS prod

COPY backend/packages/core/ backend/packages/core/
COPY backend/app/           backend/app/
COPY backend/pyproject.toml backend/
COPY skills/                skills/
COPY config.example.yaml    config.yaml

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --retries 10 --timeout 60 \
    "langchain>=1.2.0" \
    "langchain-openai>=1.1.0" \
    "langchain-community>=0.3.0" \
    "langgraph>=1.0.6" \
    "langgraph-checkpoint-sqlite>=3.0.0" \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.34.0" \
    "python-dotenv>=1.1.0" \
    "pydantic>=2.10.0" \
    "pyyaml>=6.0.0" \
    "httpx>=0.28.0" \
    "tiktoken>=0.8.0" \
    "asyncpg>=0.30.0" \
    "sse-starlette>=2.1.0" \
    "python-multipart>=0.0.26" \
    && pip install -e 'backend/packages/core[knowledge]'

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8001/health/ready || exit 1

CMD ["python", "-m", "uvicorn", "app.gateway.app:app", \
     "--host", "0.0.0.0", "--port", "8001", "--workers", "2"]
