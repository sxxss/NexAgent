from __future__ import annotations

import json

import pytest
from fastapi import HTTPException


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeModel:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def ainvoke(self, messages):
        return _FakeMessage(json.dumps(self.payload, ensure_ascii=False))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_generates_agent_draft_from_conversation(monkeypatch):
    from app.gateway.routers import creator

    payload = {
        "message": "已经整理成可保存的客服 Agent。",
        "ready_to_save": True,
        "summary": "客服质检 Agent",
        "draft": {
            "name": "客服质检",
            "description": "检查客服对话质量并给出改进建议。",
            "system_prompt": "你是客服质检 Agent。按评分表检查对话并输出改进建议。",
            "reasoning_mode": "deep",
            "allow_subagents": False,
        },
    }

    async def fake_loader(*args, **kwargs):
        return _FakeModel(payload)

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_loader)

    result = await creator.creator_chat(
        creator.CreatorChatRequest(kind="agent", message="我要一个客服质检 Agent")
    )

    assert result["kind"] == "agent"
    assert result["message"] == "已经整理成可保存的客服 Agent。"
    assert result["ready_to_save"] is True
    assert result["draft"]["name"] == "客服质检"
    assert result["draft"]["base_type"] == "chatbot"
    assert result["draft"]["reasoning_mode"] == "deep"
    assert result["draft"]["allow_subagents"] is False
    assert result["draft"]["mcp_ids"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_expands_thin_agent_prompt_into_usable_system_prompt(monkeypatch):
    from app.gateway.routers import creator

    payload = {
        "message": "已生成合同审阅 Agent。",
        "ready_to_save": True,
        "summary": "合同审阅 Agent",
        "draft": {
            "name": "合同审阅",
            "description": "审阅合同风险并给出修改建议。",
            "system_prompt": "你是合同审阅 Agent，帮助用户审合同。",
        },
    }

    async def fake_loader(*args, **kwargs):
        return _FakeModel(payload)

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_loader)

    result = await creator.creator_chat(
        creator.CreatorChatRequest(kind="agent", message="我要一个能审阅合同风险、输出风险等级和修改建议的 Agent")
    )

    prompt = result["draft"]["system_prompt"]
    assert "角色定位" in prompt
    assert "核心职责" in prompt
    assert "工作流程" in prompt
    assert "输出格式" in prompt
    assert "边界" in prompt
    assert "合同" in prompt
    assert len(prompt) > 500


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_adds_agent_tools_when_user_requests_tools(monkeypatch):
    from app.gateway.routers import creator

    payload = {
        "message": "我已根据当前对话整理出一版可保存成品草案。",
        "ready_to_save": True,
        "summary": "客服质检 Agent",
        "draft": {
            "name": "客服质检",
            "description": "检查客服对话质量并给出改进建议。",
            "tools": [],
        },
    }

    async def fake_loader(*args, **kwargs):
        return _FakeModel(payload)

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_loader)

    existing = creator._normalize_agent_draft("帮我做一个客服质检 Agent", payload["draft"])
    result = await creator.creator_chat(
        creator.CreatorChatRequest(
            kind="agent",
            message="添加一些工具",
            draft=existing,
            messages=[
                creator.CreatorChatMessage(role="user", content="帮我做一个客服质检 Agent"),
            ],
        )
    )

    assert {"knowledge_search", "web_search", "web_fetch", "execute_python"}.issubset(set(result["draft"]["tools"]))
    assert "已添加工具" in result["message"]
    assert "knowledge_search" in result["draft"]["system_prompt"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_returns_agent_quality_and_resource_plan(monkeypatch):
    from app.gateway.routers import creator

    payload = {
        "message": "已生成可保存的合同审阅 Agent。",
        "ready_to_save": True,
        "summary": "合同审阅 Agent",
        "draft": {
            "name": "合同审阅",
            "description": "审阅合同风险并给出修改建议。",
            "system_prompt": "你是合同审阅 Agent。",
            "tools": ["web_search"],
            "kb_ids": ["contracts-kb"],
            "skill_ids": ["contract-review"],
            "mcp_ids": ["legal-mcp"],
        },
    }

    async def fake_loader(*args, **kwargs):
        return _FakeModel(payload)

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_loader)

    result = await creator.creator_chat(
        creator.CreatorChatRequest(kind="agent", message="我要一个合同审阅 Agent，需要知识库、Skill 和 MCP")
    )

    quality = result["quality"]
    resource_plan = result["resource_plan"]

    assert quality["status"] in {"ready", "review"}
    assert quality["score"] >= 80
    assert any(item["id"] == "system_prompt" for item in quality["checks"])
    assert any(item["id"] == "save_target" and item["status"] == "pass" for item in quality["checks"])
    assert resource_plan["counts"]["tools"] >= 1
    assert resource_plan["counts"]["kb_ids"] == 1
    assert resource_plan["counts"]["skill_ids"] == 1
    assert resource_plan["counts"]["mcp_ids"] == 1
    assert any(item["kind"] == "tool" and item["id"] == "web_search" for item in resource_plan["items"])
    assert any(item["kind"] == "knowledge" and item["id"] == "contracts-kb" for item in resource_plan["items"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_generates_skill_draft_with_installable_metadata(monkeypatch):
    from app.gateway.routers import creator

    payload = {
        "message": "Skill 初稿已经可保存。",
        "ready_to_save": True,
        "summary": "weekly-report skill",
        "draft": {
            "id": "Weekly Report!!",
            "name": "Weekly Report",
            "description": "Turn weekly notes into a concise report.",
            "content": "# Weekly Report\n\n## Workflow\n1. Read notes.\n2. Produce report.",
            "tags": ["writing", "report"],
            "required_tools": ["web_search"],
        },
    }

    async def fake_loader(*args, **kwargs):
        return _FakeModel(payload)

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_loader)

    result = await creator.creator_chat(
        creator.CreatorChatRequest(kind="skill", message="做一个周报 Skill")
    )

    assert result["kind"] == "skill"
    assert result["ready_to_save"] is True
    assert result["draft"]["id"] == "weekly-report"
    assert result["draft"]["name"] == "Weekly Report"
    assert result["draft"]["version"] == "0.1.0"
    assert result["draft"]["tags"] == ["writing", "report"]
    assert result["draft"]["required_tools"] == ["web_search"]
    assert result["draft"]["required_mcp_ids"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_returns_skill_quality_and_resource_plan(monkeypatch):
    from app.gateway.routers import creator

    payload = {
        "message": "Skill 草稿已经可保存。",
        "ready_to_save": True,
        "summary": "合同审阅 Skill",
        "draft": {
            "id": "contract-review",
            "name": "合同审阅",
            "description": "审阅合同风险并输出证据和修改建议。",
            "content": "# 合同审阅\n\n审阅合同。",
            "tags": ["legal", "review"],
            "required_tools": ["web_search", "web_fetch"],
            "required_mcp_ids": ["legal-mcp"],
            "skill_dependencies": ["knowledge-base"],
        },
    }

    async def fake_loader(*args, **kwargs):
        return _FakeModel(payload)

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_loader)

    result = await creator.creator_chat(
        creator.CreatorChatRequest(kind="skill", message="做一个合同审阅 Skill，需要网页搜索和法律 MCP")
    )

    quality = result["quality"]
    resource_plan = result["resource_plan"]

    assert quality["status"] in {"ready", "review"}
    assert quality["score"] >= 80
    assert any(item["id"] == "skill_content" for item in quality["checks"])
    assert any(item["id"] == "installable_metadata" and item["status"] == "pass" for item in quality["checks"])
    assert resource_plan["counts"] == {"required_tools": 2, "required_mcp_ids": 1, "skill_dependencies": 1}
    assert any(item["kind"] == "tool" and item["id"] == "web_search" for item in resource_plan["items"])
    assert any(item["kind"] == "mcp" and item["id"] == "legal-mcp" for item in resource_plan["items"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_expands_thin_skill_content_into_installable_skill(monkeypatch):
    from app.gateway.routers import creator

    payload = {
        "message": "Skill 初稿已经可保存。",
        "ready_to_save": True,
        "summary": "contract-review skill",
        "draft": {
            "id": "contract-review",
            "name": "Contract Review",
            "description": "审阅合同风险并输出修改建议。",
            "content": "# Contract Review\n\n审阅合同。",
        },
    }

    async def fake_loader(*args, **kwargs):
        return _FakeModel(payload)

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_loader)

    result = await creator.creator_chat(
        creator.CreatorChatRequest(kind="skill", message="做一个合同审阅 Skill，需要风险等级、证据和修改建议")
    )

    content = result["draft"]["content"]
    assert content.startswith("# Contract Review")
    assert "## 适用场景 / 触发条件" in content
    assert "## 输入" in content
    assert "## 工作流程" in content
    assert "## 输出格式" in content
    assert "## 质量检查" in content
    assert "## 示例" in content
    assert "风险等级" in content
    assert len(content) > 700


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_adds_skill_required_tools_when_user_requests_tools(monkeypatch):
    from app.gateway.routers import creator

    payload = {
        "message": "我已根据当前对话整理出一版可保存成品草案。",
        "ready_to_save": True,
        "summary": "合同审阅 Skill",
        "draft": {
            "id": "contract-review",
            "name": "合同审阅",
            "description": "审阅合同风险。",
            "required_tools": [],
        },
    }

    async def fake_loader(*args, **kwargs):
        return _FakeModel(payload)

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", fake_loader)

    existing = creator._normalize_skill_draft("做一个合同审阅 Skill", payload["draft"])
    result = await creator.creator_chat(
        creator.CreatorChatRequest(
            kind="skill",
            message="添加网页搜索和 Python 分析工具",
            draft=existing,
            messages=[
                creator.CreatorChatMessage(role="user", content="做一个合同审阅 Skill"),
            ],
        )
    )

    assert {"web_search", "web_fetch", "execute_python"}.issubset(set(result["draft"]["required_tools"]))
    assert "已添加工具" in result["message"]
    assert "web_search" in result["draft"]["content"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_rejects_mcp_kind():
    from app.gateway.routers import creator

    with pytest.raises(HTTPException) as exc:
        await creator.creator_chat(creator.CreatorChatRequest(kind="mcp", message="创建 MCP"))

    assert exc.value.status_code == 404
    assert "MCP" in str(exc.value.detail)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_legacy_mcp_endpoints_are_disabled():
    from app.gateway.routers import creator

    with pytest.raises(HTTPException) as draft_exc:
        await creator.draft_mcp(creator.DraftRequest(goal="创建 MCP"))
    with pytest.raises(HTTPException) as save_exc:
        await creator.save_mcp(creator.SaveRequest(draft={}))

    assert draft_exc.value.status_code == 404
    assert save_exc.value.status_code == 404


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_falls_back_to_usable_skill_draft_when_model_fails(monkeypatch):
    from app.gateway.routers import creator

    async def broken_loader(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", broken_loader)

    result = await creator.creator_chat(
        creator.CreatorChatRequest(kind="skill", message="帮我做一个邮件总结 Skill")
    )

    assert result["kind"] == "skill"
    assert result["ready_to_save"] is True
    assert result["draft"]["id"].startswith("skill-")
    assert "邮件总结" in result["draft"]["description"]
    content = result["draft"]["content"]
    assert content.startswith("#")
    assert "## 适用场景 / 触发条件" in content
    assert "## 工作流程" in content
    assert "## 输出格式" in content
    assert "## 质量检查" in content
    assert "provider unavailable" not in result["message"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_falls_back_to_usable_agent_draft_from_conversation(monkeypatch):
    from app.gateway.routers import creator

    async def broken_loader(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", broken_loader)

    result = await creator.creator_chat(
        creator.CreatorChatRequest(
            kind="agent",
            message="输出要包含风险等级、证据引用和修改建议",
            messages=[
                creator.CreatorChatMessage(role="user", content="我要做一个合同审阅 Agent"),
                creator.CreatorChatMessage(role="assistant", content="好的，我会整理合同审阅职责。"),
                creator.CreatorChatMessage(role="user", content="重点看付款条款、违约责任和自动续约。"),
            ],
        )
    )

    prompt = result["draft"]["system_prompt"]
    assert result["kind"] == "agent"
    assert result["ready_to_save"] is True
    assert "合同审阅" in result["draft"]["description"]
    assert "付款条款" in prompt
    assert "违约责任" in prompt
    assert "风险等级" in prompt
    assert "角色定位" in prompt
    assert "质量标准" in prompt
    assert len(prompt) > 500


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_fallback_merges_new_agent_requirements_into_existing_draft(monkeypatch):
    from app.gateway.routers import creator

    async def broken_loader(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", broken_loader)

    existing = creator._normalize_agent_draft(
        "我要做一个合同审阅 Agent",
        {
            "name": "合同审阅",
            "description": "审阅合同风险。",
        },
    )

    result = await creator.creator_chat(
        creator.CreatorChatRequest(
            kind="agent",
            message="再添加：输出风险等级、证据引用和逐条修改建议",
            draft=existing,
            messages=[
                creator.CreatorChatMessage(role="user", content="我要做一个合同审阅 Agent"),
            ],
        )
    )

    prompt = result["draft"]["system_prompt"]
    assert "风险等级" in prompt
    assert "证据引用" in prompt
    assert "逐条修改建议" in prompt
    assert "已有草案要点" in prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_creator_chat_fallback_merges_new_skill_requirements_into_existing_draft(monkeypatch):
    from app.gateway.routers import creator

    async def broken_loader(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("nexagent.models.factory.load_chat_model_async", broken_loader)

    existing = creator._normalize_skill_draft(
        "做一个合同审阅 Skill",
        {
            "id": "contract-review",
            "name": "合同审阅",
            "description": "审阅合同风险。",
        },
    )

    result = await creator.creator_chat(
        creator.CreatorChatRequest(
            kind="skill",
            message="再添加：输出风险等级、证据引用和逐条修改建议",
            draft=existing,
            messages=[
                creator.CreatorChatMessage(role="user", content="做一个合同审阅 Skill"),
            ],
        )
    )

    content = result["draft"]["content"]
    assert "风险等级" in content
    assert "证据引用" in content
    assert "逐条修改建议" in content
    assert "已有草案要点" in content
