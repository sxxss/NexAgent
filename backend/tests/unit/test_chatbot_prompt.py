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
    assert "Only Skills configured on the current Agent or run are listed later in this prompt" in prompt
    assert "/mnt/skills/<skill-id>/scripts/..." in prompt
    assert "workspace mirror" not in prompt
    assert "Skill evolution policy" in prompt


@pytest.mark.unit
def test_chatbot_prompt_uses_wiki_knowledge_base_name():
    from nexagent.agents.builtin.chatbot.agent import _build_system_prompt
    from nexagent.agents.context import BaseContext

    prompt = _build_system_prompt(BaseContext(user_id=""))

    assert "Wiki 知识库" in prompt
    assert "LLM Wiki" not in prompt


@pytest.mark.unit
def test_chatbot_prompt_does_not_auto_discover_enabled_skills(monkeypatch, tmp_path):
    from nexagent.agents.builtin.chatbot.agent import _build_system_prompt
    from nexagent.agents.context import BaseContext

    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "public" / "auto-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
id: auto-skill
name: Auto Skill
description: Should only appear when configured.
version: 0.1.0
---

# Auto Skill
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(skills_root))

    prompt = _build_system_prompt(BaseContext(user_id="", skills=[]))

    assert "## Skills System" not in prompt
    assert "Auto Skill" not in prompt
    assert "/mnt/skills/auto-skill/SKILL.md" not in prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prepare_context_skills_does_not_auto_sync_enabled_skills(monkeypatch, tmp_path):
    from nexagent.agents.builtin.chatbot.agent import _prepare_context_skills
    from nexagent.agents.context import BaseContext
    from nexagent.config import reset_config_cache
    from nexagent.sandbox.sandbox import VirtualPathTranslator
    from nexagent.skills.loader import SkillLoader
    from nexagent.skills.runtime import prepare_skill_runtime

    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "public" / "auto-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
id: auto-skill
name: Auto Skill
description: Should only be synced when configured.
version: 0.1.0
---

# Auto Skill
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    sandbox_root = tmp_path / "sandbox-root"
    config_path.write_text(
        f"""
sandbox:
  enabled: true
  provider: local
  local:
    base_dir: {sandbox_root}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(skills_root))
    monkeypatch.setenv("NEXAGENT_CONFIG_PATH", str(config_path))
    reset_config_cache()

    try:
        skill = SkillLoader().load("auto-skill")
        assert skill is not None
        context = BaseContext(user_id="", thread_id="thread-no-skills", skills=[])
        skills_runtime = VirtualPathTranslator(str(sandbox_root)).thread_root(context.thread_id) / "skills"
        prepare_skill_runtime(context.thread_id, [skill])
        assert (skills_runtime / "auto-skill" / "SKILL.md").exists()

        await _prepare_context_skills(context)
    finally:
        reset_config_cache()

    assert not (skills_runtime / "auto-skill").exists()
