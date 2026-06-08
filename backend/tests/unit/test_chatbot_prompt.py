from __future__ import annotations

import pytest


@pytest.mark.unit
def test_chatbot_prompt_includes_runtime_model_metadata():
    from nexagent.agents.builtin.chatbot.agent import _build_system_prompt
    from nexagent.agents.context import BaseContext

    prompt = _build_system_prompt(
        BaseContext(
            agent_name="Default Agent",
            model="aliyun::qwen-plus",
            user_id="",
        )
    )

    assert "## Runtime Metadata" in prompt
    assert "Current Agent: Default Agent" in prompt
    assert "Current Model: aliyun::qwen-plus" in prompt
    assert "Do not claim that you cannot see the model configuration" in prompt


@pytest.mark.unit
def test_chatbot_prompt_requires_skill_creator_standard():
    from nexagent.agents.builtin.chatbot.agent import _build_system_prompt
    from nexagent.agents.context import BaseContext

    prompt = _build_system_prompt(BaseContext(user_id=""))

    assert "Anthropic skill-creator standard" in prompt
    assert "progressive disclosure" in prompt
    assert "test-cases/" in prompt
    assert "evals/evals.json" in prompt
    assert "scripts/" in prompt
    assert "ordinary files" in prompt


@pytest.mark.unit
def test_chatbot_prompt_enforces_managed_skill_lifecycle_tools():
    from nexagent.agents.builtin.chatbot.agent import _build_system_prompt
    from nexagent.agents.context import BaseContext

    prompt = _build_system_prompt(BaseContext(user_id=""))

    assert "## Skill Lifecycle Policy" in prompt
    assert "use list_skills, read_skill, and skill_manage as the authoritative tools" in prompt
    assert "Prefer action=patch over action=edit" in prompt
    assert "verify with read_skill" in prompt
    assert "Do not search managed Skill folders with generic filesystem" in prompt
    assert "running bash/execute_python" in prompt
    assert "MCP filesystem tools such as ls, list_directory" in prompt
    assert "Generic file tools are only for user workspace/repository files unrelated to managed Skills" in prompt
    assert "selected Skills are listed later in this prompt with `/mnt/skills`" in prompt
    assert "workspace mirror `skills/<skill-id>/...`" in prompt
    assert "Skill evolution policy" in prompt
