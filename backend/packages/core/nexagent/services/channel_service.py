"""Generic IM channel adapters for Telegram, Feishu, WeChat, and custom webhooks."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class ChannelSpec:
    id: str
    name: str
    description: str
    webhook_path: str
    enabled: bool = True


@dataclass
class ChannelMessage:
    id: str
    channel: str
    direction: str
    user_id: str
    thread_id: str
    text: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    raw: dict = field(default_factory=dict)


_CHANNELS: dict[str, ChannelSpec] = {
    "generic": ChannelSpec(
        id="generic",
        name="Generic Webhook",
        description="Provider-neutral JSON webhook for custom integrations.",
        webhook_path="/api/channels/generic/webhook",
    ),
    "telegram": ChannelSpec(
        id="telegram",
        name="Telegram",
        description="Telegram bot webhook adapter using normalized text payloads.",
        webhook_path="/api/channels/telegram/webhook",
    ),
    "feishu": ChannelSpec(
        id="feishu",
        name="Feishu",
        description="Feishu bot webhook adapter using normalized text payloads.",
        webhook_path="/api/channels/feishu/webhook",
    ),
    "wechat": ChannelSpec(
        id="wechat",
        name="WeChat",
        description="WeChat bot webhook adapter using normalized text payloads.",
        webhook_path="/api/channels/wechat/webhook",
    ),
    "wecom": ChannelSpec(
        id="wecom",
        name="WeCom",
        description="WeCom bot webhook adapter using normalized text payloads.",
        webhook_path="/api/channels/wecom/webhook",
    ),
    "slack": ChannelSpec(
        id="slack",
        name="Slack",
        description="Slack webhook adapter using normalized text payloads.",
        webhook_path="/api/channels/slack/webhook",
    ),
}

_MESSAGES: list[ChannelMessage] = []


def list_channels() -> list[dict]:
    """Return all configured channel adapters."""
    return [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "webhook_path": item.webhook_path,
            "enabled": item.enabled,
        }
        for item in _CHANNELS.values()
    ]


def get_channel(channel: str) -> ChannelSpec:
    try:
        return _CHANNELS[channel]
    except KeyError as exc:
        available = ", ".join(sorted(_CHANNELS))
        raise ValueError(f"Unknown channel '{channel}'. Available: {available}") from exc


async def handle_inbound_message(
    *,
    channel: str,
    text: str,
    user_id: str = "anonymous",
    thread_id: str | None = None,
    agent: str = "chatbot",
    model: str | None = None,
    tools: list[str] | None = None,
    kb_ids: list[str] | None = None,
    raw: dict | None = None,
) -> dict:
    """Normalize an inbound channel message and dispatch it to an agent."""
    spec = get_channel(channel)
    normalized_text = text.strip() or _extract_text(raw or {})
    if not normalized_text:
        raise ValueError("Inbound channel message has no text content")

    from nexagent.services.chat_service import invoke_chat

    thread = thread_id or f"{spec.id}-{user_id}-{uuid.uuid4()}"
    _publish(
        ChannelMessage(
            id=str(uuid.uuid4()),
            channel=spec.id,
            direction="inbound",
            user_id=user_id,
            thread_id=thread,
            text=normalized_text,
            raw=raw or {},
        )
    )
    result = await invoke_chat(
        message=normalized_text,
        agent_name=agent,
        thread_id=thread,
        context_overrides={
            "model": model,
            "user_id": f"{spec.id}:{user_id}",
            "tools": tools or [],
            "kb_ids": kb_ids or [],
        },
    )
    response = str(result.get("response", ""))
    _publish(
        ChannelMessage(
            id=str(uuid.uuid4()),
            channel=spec.id,
            direction="outbound",
            user_id=user_id,
            thread_id=thread,
            text=response,
        )
    )
    return {
        "channel": spec.id,
        "user_id": user_id,
        "thread_id": result.get("thread_id"),
        "agent": result.get("agent", agent),
        "response": response,
        "outbound": format_outbound(spec.id, response),
    }


def list_channel_messages(channel: str | None = None, limit: int = 100) -> list[dict]:
    messages = [item for item in _MESSAGES if channel is None or item.channel == channel]
    return [asdict(item) for item in messages[-limit:]]


def format_outbound(channel: str, text: str) -> dict:
    if channel == "telegram":
        return {"method": "sendMessage", "text": text}
    if channel in {"feishu", "wecom"}:
        return {"msg_type": "text", "content": {"text": text}}
    if channel == "slack":
        return {"text": text}
    return {"text": text}


def _extract_text(raw: dict) -> str:
    """Best-effort extraction from common provider payload shapes."""
    candidates = [
        raw.get("text"),
        raw.get("content"),
        raw.get("message", {}).get("text") if isinstance(raw.get("message"), dict) else None,
        raw.get("message", {}).get("content") if isinstance(raw.get("message"), dict) else None,
        raw.get("event", {}).get("message", {}).get("content")
        if isinstance(raw.get("event"), dict)
        else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _publish(message: ChannelMessage) -> None:
    _MESSAGES.append(message)
    if len(_MESSAGES) > 1000:
        del _MESSAGES[: len(_MESSAGES) - 1000]
