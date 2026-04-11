"""Database initialisation — creates tables and seeds built-in agents."""

from __future__ import annotations

import hashlib
import logging

from nexagent.db.base import Base, engine

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Create all tables and insert default records if they don't exist."""
    import nexagent.db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_lightweight_migrations(conn)
    logger.info("Database initialised")

    await _seed_builtin_agents()
    await _seed_model_providers_from_config()


async def _seed_builtin_agents() -> None:
    """Insert the two built-in agent configs if not already present."""
    from nexagent.db.models import AgentConfig
    from nexagent.db.session import AsyncSessionLocal

    BUILTIN = [
        AgentConfig(
            id="chatbot",
            name="智能对话",
            description="通用对话助手，支持模型切换、流式输出、知识库检索和工具调用。",
            base_type="chatbot",
            is_builtin=True,
            allow_subagents=True,
            avatar_color="indigo",
        ),
        AgentConfig(
            id="deep_research",
            name="深度研究",
            description="多阶段研究 Agent：自动规划、多轮检索、生成结构化报告。",
            base_type="deep_research",
            is_builtin=True,
            allow_subagents=True,
            avatar_color="violet",
        ),
    ]

    async with AsyncSessionLocal() as session:
        for agent in BUILTIN:
            if agent.id == "chatbot":
                agent.name = "智能对话"
                agent.description = "通用对话 Agent，支持模型切换、流式输出、知识库检索和工具调用。"
                agent.reasoning_mode = "balanced"
                agent.avatar_color = "emerald"
            elif agent.id == "deep_research":
                agent.name = "深度研究"
                agent.description = "多阶段研究 Agent，自动规划、检索、分析并生成结构化报告。"
                agent.reasoning_mode = "deep"
            exists = await session.get(AgentConfig, agent.id)
            if not exists:
                session.add(agent)
            elif agent.id == "chatbot":
                exists.name = "智能对话"
                exists.description = "通用对话 Agent，支持模型切换、流式输出、知识库检索和工具调用。"
                exists.reasoning_mode = exists.reasoning_mode or "balanced"
                exists.avatar_color = exists.avatar_color or "emerald"
            elif agent.id == "deep_research":
                exists.name = "深度研究"
                exists.description = "多阶段研究 Agent，自动规划、检索、分析并生成结构化报告。"
                exists.reasoning_mode = exists.reasoning_mode or "deep"
        await session.commit()

    logger.debug("Built-in agents seeded")


async def _seed_model_providers_from_config() -> None:
    """Mirror YAML model providers into DB once so Settings is editable from day one."""
    try:
        from nexagent.config import get_config
        from nexagent.db.crypto import encrypt_key
        from nexagent.db.models import ModelProvider
        from nexagent.db.session import AsyncSessionLocal
    except Exception as exc:
        logger.debug("Skipping provider seed: %s", exc)
        return

    cfg = get_config()
    grouped: dict[str, dict] = {}
    for model in cfg.models:
        provider_type = model.provider.lower()
        base_url = model.base_url or ""
        key = f"{provider_type}:{base_url}"
        suffix = hashlib.sha1(base_url.encode("utf-8")).hexdigest()[:8] if base_url else ""
        item = grouped.setdefault(
            key,
            {
                "id": f"config-{provider_type}" if not base_url else f"config-{provider_type}-{suffix}",
                "name": provider_type.title(),
                "provider_type": provider_type,
                "base_url": base_url,
                "api_key_env": _provider_api_key_env(provider_type, base_url),
                "api_key": model.api_key or "",
                "models": [],
                "is_default": False,
            },
        )
        if model.model not in item["models"]:
            item["models"].append(model.model)
        if model.name == cfg.default_model:
            item["is_default"] = True

    if not grouped:
        return

    async with AsyncSessionLocal() as session:
        for item in grouped.values():
            exists = await session.get(ModelProvider, item["id"])
            if exists:
                continue
            provider = ModelProvider(
                id=item["id"],
                name=item["name"],
                provider_type=item["provider_type"],
                base_url=item["base_url"] or None,
                api_key_env=item["api_key_env"] or None,
                api_key_enc=encrypt_key(item["api_key"]) if item["api_key"] else None,
                is_enabled=True,
                is_default=item["is_default"],
            )
            provider.models = item["models"]
            provider.capabilities = ["chat"]
            provider.model_configs = [
                {"id": model, "display_name": model, "type": "chat"} for model in item["models"]
            ]
            session.add(provider)
        await session.commit()

    logger.debug("Config model providers seeded")


def _provider_api_key_env(provider_type: str, base_url: str) -> str:
    text = f"{provider_type} {base_url}".lower()
    if "siliconflow" in text:
        return "SILICONFLOW_API_KEY"
    if "deepseek" in text:
        return "DEEPSEEK_API_KEY"
    if "dashscope" in text or "aliyun" in text:
        return "DASHSCOPE_API_KEY"
    if "moonshot" in text:
        return "MOONSHOT_API_KEY"
    if "openrouter" in text:
        return "OPENROUTER_API_KEY"
    if provider_type == "openai":
        return "OPENAI_API_KEY"
    return ""


async def _run_lightweight_migrations(conn) -> None:
    """Add columns introduced after the initial SQLite schema.

    This project intentionally avoids a full migration framework for now, but
    local users can have an existing .nexagent database. These idempotent
    ALTER TABLE statements keep startup compatible.
    """
    from sqlalchemy import text

    migrations = [
        "ALTER TABLE model_providers ADD COLUMN models_endpoint VARCHAR(256) DEFAULT '/models'",
        "ALTER TABLE model_providers ADD COLUMN api_key_env VARCHAR(128)",
        "ALTER TABLE model_providers ADD COLUMN capabilities_json TEXT",
        "ALTER TABLE model_providers ADD COLUMN model_configs_json TEXT",
        "ALTER TABLE agent_configs ADD COLUMN tools_json TEXT",
        "ALTER TABLE agent_configs ADD COLUMN reasoning_mode VARCHAR(32) DEFAULT 'balanced'",
        "ALTER TABLE invocation_logs ADD COLUMN reasoning_mode VARCHAR(32)",
        "ALTER TABLE invocation_logs ADD COLUMN raw_input_tokens INTEGER DEFAULT 0",
        "ALTER TABLE invocation_logs ADD COLUMN raw_output_tokens INTEGER DEFAULT 0",
        "ALTER TABLE invocation_logs ADD COLUMN token_source VARCHAR(32) DEFAULT 'provider_reported'",
        "ALTER TABLE invocation_logs ADD COLUMN token_estimated BOOLEAN DEFAULT 0",
        "ALTER TABLE mcp_servers ADD COLUMN disabled_tools_json TEXT",
    ]
    for sql in migrations:
        try:
            await conn.execute(text(sql))
        except Exception as exc:
            message = str(exc).lower()
            if "duplicate column" not in message and "already exists" not in message:
                logger.debug("Skipping migration '%s': %s", sql, exc)
