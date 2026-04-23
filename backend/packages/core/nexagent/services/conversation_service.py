"""Conversation persistence helpers."""

from __future__ import annotations

from datetime import datetime


def _make_title(message: str) -> str:
    title = " ".join(message.strip().split())
    if not title:
        return "新对话"
    return title[:36] + ("..." if len(title) > 36 else "")


async def ensure_conversation(
    *,
    conversation_id: str,
    user_id: str | None,
    agent_id: str,
    agent_name: str,
    model_name: str | None,
    first_message: str = "",
) -> dict:
    from nexagent.db.models import Conversation
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            conversation = Conversation(
                id=conversation_id,
                title=_make_title(first_message),
                user_id=user_id,
                agent_id=agent_id,
                agent_name=agent_name,
                model_name=model_name,
                last_message=first_message[:500],
                message_count=0,
            )
            session.add(conversation)
        else:
            conversation.agent_id = agent_id
            conversation.agent_name = agent_name
            conversation.model_name = model_name
            conversation.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(conversation)
        return conversation.to_dict()


async def append_message(
    *,
    conversation_id: str,
    role: str,
    content: str,
    tool_name: str | None = None,
    reasoning_content: str | None = None,
) -> dict:
    from nexagent.db.models import Conversation, ConversationMessage
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        message = ConversationMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_name=tool_name,
            reasoning_content=reasoning_content,
        )
        session.add(message)

        conversation = await session.get(Conversation, conversation_id)
        if conversation:
            conversation.last_message = content[:500]
            conversation.message_count = (conversation.message_count or 0) + 1
            conversation.updated_at = datetime.utcnow()
            if conversation.title == "新对话" and role == "user":
                conversation.title = _make_title(content)
        await session.commit()
        await session.refresh(message)
        return message.to_dict()


async def list_conversations(user_id: str | None = None, limit: int = 50) -> list[dict]:
    from sqlalchemy import desc, select

    from nexagent.db.models import Conversation
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        stmt = select(Conversation).where(Conversation.archived == False)  # noqa: E712
        if user_id:
            stmt = stmt.where(Conversation.user_id == user_id)
        stmt = stmt.order_by(desc(Conversation.updated_at)).limit(limit)
        result = await session.execute(stmt)
        return [item.to_dict() for item in result.scalars().all()]


async def get_conversation(conversation_id: str) -> dict | None:
    from nexagent.db.models import Conversation
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        conversation = await session.get(Conversation, conversation_id)
        return conversation.to_dict() if conversation else None


async def list_messages(conversation_id: str) -> list[dict]:
    from sqlalchemy import select

    from nexagent.db.models import ConversationMessage
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at)
        )
        return [item.to_dict() for item in result.scalars().all()]


async def update_conversation(conversation_id: str, *, title: str | None = None, archived: bool | None = None) -> dict:
    from nexagent.db.models import Conversation
    from nexagent.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            raise KeyError(conversation_id)
        if title is not None and title.strip():
            conversation.title = title.strip()
        if archived is not None:
            conversation.archived = archived
        conversation.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(conversation)
        return conversation.to_dict()


async def delete_conversation(conversation_id: str) -> None:
    await update_conversation(conversation_id, archived=True)
