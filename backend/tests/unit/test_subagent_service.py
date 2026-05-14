from __future__ import annotations

import asyncio

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subagent_run_respects_max_concurrency(monkeypatch):
    from nexagent.services import chat_service, subagent_service
    from nexagent.services.subagent_service import SubAgentTask

    running = 0
    max_seen = 0

    async def fake_resolve(task, policy=None):
        return task.agent, {}

    async def fake_invoke_chat(message, agent_name="chatbot", thread_id=None, context_overrides=None):
        nonlocal running, max_seen
        running += 1
        max_seen = max(max_seen, running)
        await asyncio.sleep(0.02)
        running -= 1
        return {"response": f"done:{message}", "thread_id": f"thread:{message}"}

    monkeypatch.setattr(subagent_service, "_resolve_task_runtime", fake_resolve)
    monkeypatch.setattr(chat_service, "invoke_chat", fake_invoke_chat)

    result = await subagent_service.run_subagents(
        [SubAgentTask(agent="chatbot", message=f"task-{index}") for index in range(5)],
        max_concurrency=2,
    )

    assert result["succeeded"] == 5
    assert result["failed"] == 0
    assert max_seen <= 2
    assert [item["index"] for item in result["results"]] == [0, 1, 2, 3, 4]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subagent_timeout_is_partial_failure(monkeypatch):
    from nexagent.services import chat_service, subagent_service
    from nexagent.services.subagent_service import SubAgentTask

    async def fake_resolve(task, policy=None):
        return task.agent, {}

    async def fake_invoke_chat(message, agent_name="chatbot", thread_id=None, context_overrides=None):
        await asyncio.sleep(0.05)
        return {"response": "late"}

    monkeypatch.setattr(subagent_service, "_resolve_task_runtime", fake_resolve)
    monkeypatch.setattr(chat_service, "invoke_chat", fake_invoke_chat)

    result = await subagent_service.run_subagents(
        [SubAgentTask(agent="chatbot", message="slow")],
        timeout_seconds=0.01,
    )

    assert result["status"] == "partial_failure"
    assert result["failed"] == 1
    assert result["results"][0]["status"] == "timed_out"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subagent_policy_filters_child_context():
    from nexagent.services.subagent_service import SubAgentPolicy, SubAgentTask, _resolve_task_runtime

    _runtime, context = await _resolve_task_runtime(
        SubAgentTask(
            agent="chatbot",
            message="bounded",
            tools=["web_search", "execute_python"],
            kb_ids=["kb-a", "kb-b"],
            mcp_ids=["github"],
            skill_ids=["writer", "private"],
        ),
        policy=SubAgentPolicy(
            allowed_agent_ids=["chatbot"],
            allowed_tools=["web_search"],
            allowed_kb_ids=["kb-b"],
            allowed_mcp_ids=[],
            allowed_skill_ids=["writer"],
        ),
    )

    assert context["tools"] == ["web_search"]
    assert context["tools_explicit"] is True
    assert context["kb_ids"] == ["kb-b"]
    assert context["mcp_ids"] == []
    assert context["skills"] == ["writer"]
    assert context["allow_subagents"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subagent_policy_blocks_disallowed_agent():
    from nexagent.services.subagent_service import SubAgentPolicy, SubAgentTask, _resolve_task_runtime

    with pytest.raises(PermissionError):
        await _resolve_task_runtime(
            SubAgentTask(agent="private-agent", message="nope"),
            policy=SubAgentPolicy(allowed_agent_ids=["chatbot"]),
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_subagent_accepts_common_deep_research_alias():
    from nexagent.services.subagent_service import SubAgentPolicy, SubAgentTask, _resolve_task_runtime

    runtime, context = await _resolve_task_runtime(
        SubAgentTask(agent="deep-research", message="research"),
        policy=SubAgentPolicy(allowed_agent_ids=["deep_research"]),
    )

    assert runtime == "deep_research"
    assert context["allow_subagents"] is False


@pytest.mark.unit
def test_subagent_model_strategy_resolution():
    from nexagent.tools.builtin.subagent import _resolve_task_model

    assert _resolve_task_model(
        requested=None,
        strategy="main_agent",
        parent_model="qwen-plus",
        custom_model=None,
    ) == "qwen-plus"
    assert _resolve_task_model(
        requested="model-picked-by-llm",
        strategy="agent_default",
        parent_model="qwen-plus",
        custom_model="glm-5",
    ) is None
    assert _resolve_task_model(
        requested=None,
        strategy="custom",
        parent_model="qwen-plus",
        custom_model="glm-5",
    ) == "glm-5"
