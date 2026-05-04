"""Channel router — generic IM webhook adapters."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()


class ChannelMessageRequest(BaseModel):
    text: str = Field(default="", description="Inbound message text")
    user_id: str = Field(default="anonymous")
    thread_id: str | None = None
    agent: str = "chatbot"
    model: str | None = None
    tools: list[str] = []
    kb_ids: list[str] = []
    raw: dict = Field(default_factory=dict)


@router.get("/")
async def list_channels():
    from nexagent.services.channel_service import list_channels as _list

    return {"channels": _list()}


@router.get("/messages")
async def list_channel_messages(channel: str | None = None, limit: int = 100):
    from nexagent.services.channel_service import list_channel_messages as _list_messages

    return {"messages": _list_messages(channel=channel, limit=limit)}


@router.post("/{channel}/webhook")
async def channel_webhook(channel: str, req: ChannelMessageRequest):
    from nexagent.services.channel_service import handle_inbound_message

    try:
        return await handle_inbound_message(
            channel=channel,
            text=req.text,
            user_id=req.user_id,
            thread_id=req.thread_id,
            agent=req.agent,
            model=req.model,
            tools=req.tools,
            kb_ids=req.kb_ids,
            raw=req.raw,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
