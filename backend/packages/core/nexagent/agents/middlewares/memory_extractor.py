"""Memory extractor — automatically save notable information from conversations.

Activated when an AgentConfig has memory_enabled=True.
Runs after each successful turn, extracting facts/preferences/episodes via LLM.
"""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """Analyze this conversation excerpt and extract memorable information about the user.
Return a JSON array of memory items. Each item must have:
{"type": "fact|preference|episode", "key": "<short label>", "value": "<content>", "importance": 0.0-1.0}
- fact: objective info the user stated (name, role, location, tech stack…)
- preference: how the user likes things done (language, style, format…)
- episode: a summary of what was discussed or decided

If nothing is worth remembering, return [].
Only return the JSON array, no extra text.

Conversation:
{conversation}"""


async def extract_and_save(
    user_id: str,
    agent_id: str,
    model_name: str,
    conversation_text: str,
) -> list[dict]:
    """Run memory extraction and persist results. Returns saved entries."""
    if not conversation_text.strip():
        return []

    try:
        items = await _extract(model_name, conversation_text)
    except Exception as exc:
        logger.debug("Memory extraction failed: %s", exc)
        return []

    if not items:
        return []

    saved = []
    try:
        from nexagent.agents.memory import upsert_fact
        from nexagent.db.models import MemoryEntry
        from nexagent.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            for item in items:
                entry = MemoryEntry(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    agent_id=agent_id,
                    memory_type=item.get("type", "fact"),
                    key=str(item.get("key", ""))[:256],
                    value=str(item.get("value", "")),
                    source="agent",
                    importance=float(item.get("importance", 0.5)),
                )
                session.add(entry)
                saved.append(entry.to_dict())
                upsert_fact(
                    user_id=user_id,
                    content=str(item.get("value", "")),
                    category=_category(item.get("type", "fact")),
                    confidence=float(item.get("importance", 0.5)),
                    source=agent_id,
                )
            await session.commit()
        logger.debug("Saved %d memory entries for user %s", len(saved), user_id)
    except Exception as exc:
        logger.warning("Failed to save memory entries: %s", exc)

    return saved


async def _extract(model_name: str, conversation: str) -> list[dict]:
    from langchain_core.messages import HumanMessage

    from nexagent.models.factory import load_chat_model_async

    llm = await load_chat_model_async(model_name)
    prompt = _EXTRACTION_PROMPT.format(conversation=conversation[:3000])
    response = await llm.ainvoke([HumanMessage(content=prompt)])

    content = response.content if hasattr(response, "content") else str(response)
    # Strip markdown code fences if present
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    items = json.loads(content)
    if not isinstance(items, list):
        return []
    return items


def _category(value: str) -> str:
    mapping = {"fact": "knowledge", "preference": "preference", "episode": "context"}
    return mapping.get(str(value), "context")
