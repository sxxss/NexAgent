"""Conversation history API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ConversationCreate(BaseModel):
    title: str | None = None
    user_id: str | None = None
    agent_id: str = "chatbot"
    agent_name: str = "chatbot"
    model_name: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    archived: bool | None = None


@router.get("/")
async def list_items(user_id: str | None = None, limit: int = 50):
    from nexagent.services.conversation_service import list_conversations

    return {"conversations": await list_conversations(user_id=user_id, limit=limit)}


@router.post("/", status_code=201)
async def create_item(body: ConversationCreate):
    import uuid

    from nexagent.services.conversation_service import ensure_conversation, update_conversation

    conversation_id = str(uuid.uuid4())
    item = await ensure_conversation(
        conversation_id=conversation_id,
        user_id=body.user_id,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        model_name=body.model_name,
        first_message=body.title or "",
    )
    if body.title:
        item = await update_conversation(conversation_id, title=body.title)
    return item


@router.get("/{conversation_id}")
async def get_item(conversation_id: str):
    from nexagent.services.conversation_service import get_conversation, list_messages

    conversation = await get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversation": conversation, "messages": await list_messages(conversation_id)}


@router.patch("/{conversation_id}")
async def update_item(conversation_id: str, body: ConversationUpdate):
    from nexagent.services.conversation_service import update_conversation

    try:
        return await update_conversation(conversation_id, title=body.title, archived=body.archived)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found") from None


@router.delete("/{conversation_id}", status_code=204)
async def delete_item(conversation_id: str):
    from nexagent.services.conversation_service import delete_conversation

    try:
        await delete_conversation(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found") from None
