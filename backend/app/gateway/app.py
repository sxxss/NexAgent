"""NexAgent Gateway - FastAPI application."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.gateway.routers import (
    agents,
    artifacts,
    auth,
    channels,
    chat,
    conversations,
    creator,
    dashboard,
    eval,
    knowledge,
    mcp,
    media,
    memory,
    settings,
    skills,
    tasks,
)

APP_VERSION = os.environ.get("NEXAGENT_VERSION", "0.1.0")
STARTED_AT = time.time()
logger = logging.getLogger(__name__)


def _load_dotenv() -> str | None:
    """Load .env from the project root if python-dotenv is available."""
    try:
        from dotenv import load_dotenv

        candidates = [
            Path(__file__).parents[3] / ".env",
            Path(__file__).parents[2] / ".env",
            Path.cwd() / ".env",
            Path.cwd().parent / ".env",
        ]
        for path in candidates:
            if path.exists():
                load_dotenv(path, override=False)
                return str(path)
    except ImportError:
        pass
    return None


DOTENV_PATH = _load_dotenv()


def _parse_cors_origins() -> list[str]:
    raw = os.environ.get("NEXAGENT_CORS_ORIGINS", "*")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or ["*"]


def _gateway_status() -> dict:
    return {
        "status": "ok",
        "service": "nexagent-gateway",
        "version": APP_VERSION,
        "uptime_seconds": round(time.time() - STARTED_AT, 3),
    }


def _safe_config_snapshot() -> dict:
    """Return non-secret runtime configuration for diagnostics."""
    from nexagent.config import get_config, get_config_diagnostics

    cfg = get_config()
    diagnostics = get_config_diagnostics()
    data_dir = os.environ.get("NEXAGENT_DATA_DIR", ".nexagent")
    return {
        "debug": cfg.debug,
        "diagnostics": diagnostics.to_dict(),
        "default_model": cfg.default_model,
        "model_count": len(cfg.models),
        "models": [
            {
                "name": model.name,
                "display_name": model.display_name,
                "provider": model.provider,
                "model": model.model,
                "base_url": model.base_url,
                "supports_streaming": model.supports_streaming,
                "api_key_configured": bool(model.api_key),
            }
            for model in cfg.models
        ],
        "knowledge": {
            "milvus_host": cfg.knowledge.milvus_host,
            "milvus_port": cfg.knowledge.milvus_port,
            "neo4j_uri": cfg.knowledge.neo4j_uri,
            "neo4j_user": cfg.knowledge.neo4j_user,
            "neo4j_password_configured": bool(cfg.knowledge.neo4j_password),
            "embed_model": cfg.knowledge.embed_model,
            "embed_dimension": cfg.knowledge.embed_dimension,
            "embed_api_key_configured": bool(cfg.knowledge.embed_api_key),
        },
        "web_search": {
            "provider": cfg.web_search.provider,
            "preferred_provider": cfg.web_search.preferred_provider,
            "enabled_providers": cfg.web_search.enabled_providers,
            "max_results": cfg.web_search.max_results,
            "fetch_max_chars": cfg.web_search.fetch_max_chars,
            "tavily_api_key_configured": bool(cfg.web_search.tavily_api_key),
        },
        "mcp_server_count": len(cfg.mcp_servers),
        "sandbox": {
            "enabled": cfg.sandbox.enabled,
            "timeout_seconds": cfg.sandbox.timeout_seconds,
            "max_output_chars": cfg.sandbox.max_output_chars,
        },
        "data_dir": data_dir,
    }


async def _check_database() -> dict:
    from nexagent.db.session import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}


def _check_data_dir(path_value: str) -> dict:
    data_dir = Path(path_value)
    data_dir.mkdir(parents=True, exist_ok=True)
    probe = data_dir / ".nexagent-ready"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    return {"status": "ok", "path": str(data_dir)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown hooks."""
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("NEXAGENT_DEBUG") == "1" else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("NexAgent Gateway starting up")
    if DOTENV_PATH:
        logger.info("Loaded environment from %s", DOTENV_PATH)

    # Initialise database (create tables + seed built-in agents)
    try:
        from nexagent.db.init_db import init_db
        await init_db()
    except Exception as exc:
        logger.warning("Database init failed (non-fatal): %s", exc)

    yield
    logger.info("NexAgent Gateway shutting down")


app = FastAPI(
    title="NexAgent",
    description="Knowledge-enhanced AI Agent Platform - RAG + Knowledge Graph + Agent Orchestration",
    version=APP_VERSION,
    lifespan=lifespan,
)

cors_origins = _parse_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(conversations.router, prefix="/api/conversations", tags=["Conversations"])
app.include_router(creator.router, prefix="/api/creator", tags=["Creator"])
app.include_router(artifacts.router, prefix="/api/artifacts", tags=["Artifacts"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["Knowledge"])
app.include_router(media.router, prefix="/api/media", tags=["Media"])
app.include_router(agents.router, prefix="/api/agents", tags=["Agents"])
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(eval.router, prefix="/api/eval", tags=["Evaluation"])
app.include_router(memory.router, prefix="/api/memory", tags=["Memory"])
app.include_router(channels.router, prefix="/api/channels", tags=["Channels"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(mcp.router, prefix="/api/mcp", tags=["MCP"])
app.include_router(skills.router, prefix="/api/skills", tags=["Skills"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["Tasks"])


@app.get("/")
async def root():
    """Small discovery endpoint for humans and simple health probes."""
    return {
        **_gateway_status(),
        "docs_url": "/docs",
        "health_url": "/health",
        "ready_url": "/health/ready",
    }


@app.get("/health")
async def health_check():
    """Compatibility health endpoint."""
    return _gateway_status()


@app.get("/health/live")
async def liveness_check():
    """Liveness probe: process is running and serving HTTP."""
    return _gateway_status()


@app.get("/health/ready")
async def readiness_check():
    """Readiness probe: app can load config, use the DB, and write data."""
    checks: dict[str, dict] = {}
    status = "ok"
    snapshot: dict | None = None
    try:
        snapshot = _safe_config_snapshot()
        checks["config"] = {
            "status": snapshot["diagnostics"]["status"],
            "default_model": snapshot["default_model"],
            "model_count": snapshot["model_count"],
            "issues": snapshot["diagnostics"]["issues"],
        }
        if snapshot["diagnostics"]["status"] == "error":
            status = "error"
        elif snapshot["diagnostics"]["status"] == "warning" and status == "ok":
            status = "degraded"
    except Exception as exc:
        status = "error"
        checks["config"] = {"status": "error", "message": str(exc)}

    try:
        checks["database"] = await _check_database()
    except Exception as exc:
        status = "error"
        checks["database"] = {"status": "error", "message": str(exc)}

    try:
        data_dir = snapshot["data_dir"] if snapshot else os.environ.get("NEXAGENT_DATA_DIR", ".nexagent")
        checks["data_dir"] = _check_data_dir(data_dir)
    except Exception as exc:
        status = "error"
        checks["data_dir"] = {"status": "error", "message": str(exc)}

    return {**_gateway_status(), "status": status, "checks": checks}


@app.get("/api/system/info")
async def system_info():
    """Return non-secret runtime information for setup diagnostics."""
    return {**_gateway_status(), "config": _safe_config_snapshot()}


@app.get("/api/system/diagnostics")
async def system_diagnostics():
    """Return actionable startup diagnostics without exposing secret values."""
    from nexagent.config import get_config_diagnostics

    return {**_gateway_status(), "config": get_config_diagnostics().to_dict()}


@app.get("/api/models")
async def list_models():
    """List available LLM models."""
    from nexagent.config import get_config
    from nexagent.models.factory import REASONING_MODES, list_model_configs_async

    config = get_config()
    return {
        "default_model": config.default_model,
        "reasoning_modes": list(REASONING_MODES),
        "models": await list_model_configs_async(),
    }


@app.get("/api/models/capabilities")
async def list_model_capabilities():
    """Return UI-facing model capability metadata."""
    from nexagent.models.factory import list_model_configs_async

    models = await list_model_configs_async()
    return {
        "models": [
            {
                "name": item["name"],
                "display_name": item.get("display_name") or item["name"],
                "provider": item.get("provider"),
                "model": item.get("model"),
                "capabilities": item.get("capabilities", {}),
            }
            for item in models
        ]
    }
