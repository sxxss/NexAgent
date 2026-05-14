from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest


def _workspace() -> Path:
    return Path(".test-workspaces") / f"skill-manager-{uuid.uuid4().hex}"


def _patch_loader(monkeypatch, workspace: Path):
    from nexagent.skills import loader as loader_module
    from nexagent.skills.loader import SkillLoader

    class TempSkillLoader(SkillLoader):
        def __init__(self, skills_dir=None):
            super().__init__(workspace / "skills")

    monkeypatch.setattr(loader_module, "SkillLoader", TempSkillLoader)
    return TempSkillLoader


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_create_writes_to_managed_skill_dir(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    loader_cls = _patch_loader(monkeypatch, workspace)

    try:
        tool = get_skill_manage_tool()
        result = await tool.ainvoke({
            "action": "create",
            "id": "web-extractor",
            "name": "Web Extractor",
            "description": "Extract structured data from web pages.",
            "content": "# Workflow\n\nUse web_fetch, then extract fields.",
            "required_tools": ["web_fetch"],
            "files": [{"path": "references/template.md", "content": "# Template\n\n- title"}],
        })

        payload = json.loads(result)
        assert payload["ok"] is True
        assert payload["id"] == "web-extractor"
        assert (workspace / "skills" / "public" / "web-extractor" / "SKILL.md").exists()
        assert (workspace / "skills" / "public" / "web-extractor" / "references" / "template.md").exists()
        loaded = loader_cls().load("web-extractor")
        assert loaded is not None
        assert loaded.description == "Extract structured data from web pages."
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_create_writes_executable_skill_py(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        tool = get_skill_manage_tool()
        result = await tool.ainvoke({
            "action": "create",
            "id": "echo-skill",
            "name": "Echo Skill",
            "content": "# Echo\n\nUse echo_text for echoing.",
            "executable_code": '''
from langchain_core.tools import tool
from nexagent.skills.base import BaseSkill, SkillMetadata


class EchoSkill(BaseSkill):
    metadata = SkillMetadata(name="echo-skill", description="Echo text.")

    def get_tools(self):
        @tool("echo_text")
        def echo_text(text: str) -> str:
            """Echo the provided text."""
            return text

        return [echo_text]
''',
        })

        payload = json.loads(result)
        assert payload["ok"] is True
        assert payload["storage"] == "managed"
        assert "path" not in payload
        assert payload["executable"] is True
        assert payload["tools"] == ["echo_text"]
        assert payload["executable_tools"][0]["name"] == "echo_text"
        assert not any(item["path"] == "skill.py" for item in payload["files"])
        assert (workspace / "skills" / "public" / "echo-skill" / "skill.py").exists()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_requires_executable_contract(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        tool = get_skill_manage_tool()
        result = await tool.ainvoke({
            "action": "create",
            "id": "bad-skill",
            "name": "Bad Skill",
            "content": "# Bad",
            "executable_code": "print('no')",
        })

        assert result.startswith("Error:")
        assert "BaseSkill" in result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_skill_tool_returns_managed_files(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_read_skill_tool, get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        manage_tool = get_skill_manage_tool()
        await manage_tool.ainvoke({
            "action": "create",
            "id": "reader-skill",
            "name": "Reader Skill",
            "content": "# Reader\n\nUse references.",
            "files": [{"path": "references/example.md", "content": "example content"}],
            "executable_code": '''
from langchain_core.tools import tool
from nexagent.skills.base import BaseSkill, SkillMetadata


class ReaderSkill(BaseSkill):
    metadata = SkillMetadata(name="reader-skill", description="Read examples.")

    def get_tools(self):
        @tool("read_example")
        def read_example(text: str) -> str:
            """Read example text."""
            return text

        return [read_example]
''',
        })

        read_tool = get_read_skill_tool()
        result = await read_tool.ainvoke({"id": "reader-skill"})
        payload = json.loads(result)

        assert payload["id"] == "reader-skill"
        assert payload["storage"] == "managed"
        assert "path" not in payload
        assert not any(item["path"] == "skill.py" for item in payload["files"])
        assert payload["executable_tools"][0]["name"] == "read_example"
        assert any(item["path"] == "SKILL.md" for item in payload["contents"])
        assert not any(item["path"] == "references/example.md" for item in payload["contents"])

        result = await read_tool.ainvoke({"id": "reader-skill", "path": "skill.py"})
        payload = json.loads(result)
        assert payload["contents"][0]["path"] == "skill.py"
        assert "class ReaderSkill" in payload["contents"][0]["content"]

        result = await read_tool.ainvoke({"id": "reader-skill", "path": "references/example.md"})
        payload = json.loads(result)
        assert payload["contents"][0]["path"] == "references/example.md"
        assert payload["contents"][0]["content"] == "example content"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_edit_preserves_existing_support_files(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        tool = get_skill_manage_tool()
        await tool.ainvoke({
            "action": "create",
            "id": "preserve-skill",
            "name": "Preserve Skill",
            "content": "# Old",
            "files": [{"path": "references/example.md", "content": "keep me"}],
        })

        result = await tool.ainvoke({
            "action": "edit",
            "id": "preserve-skill",
            "name": "Preserve Skill",
            "content": "# New",
        })

        payload = json.loads(result)
        assert payload["ok"] is True
        assert (workspace / "skills" / "public" / "preserve-skill" / "references" / "example.md").read_text(
            encoding="utf-8"
        ) == "keep me"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_edit_allows_preserved_broken_skill_py(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        root = workspace / "skills" / "public" / "broken-executable"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text(
            "---\nid: broken-executable\nname: Broken Executable\ndescription: Broken.\n---\n\n# Old\n",
            encoding="utf-8",
        )
        (root / "skill.py").write_text("from agent.skills import BaseSkill\n", encoding="utf-8")

        tool = get_skill_manage_tool()
        result = await tool.ainvoke({
            "action": "edit",
            "id": "broken-executable",
            "name": "Broken Executable",
            "description": "Updated.",
            "content": "# Updated",
        })

        payload = json.loads(result)
        assert payload["ok"] is True
        assert payload["warning"]
        assert payload["issues"][0]["code"] == "preserved_executable_import_failed"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_rejects_foreign_skill_imports(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        tool = get_skill_manage_tool()
        result = await tool.ainvoke({
            "action": "create",
            "id": "foreign-import",
            "name": "Foreign Import",
            "content": "# Foreign",
            "executable_code": "from agent.skills import BaseSkill\n\ndef get_tools(self):\n    return []",
        })

        assert result.startswith("Error:")
        assert "nexagent.skills.base" in result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_skills_tool_filters_managed_skills(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_list_skills_tool, get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        manage_tool = get_skill_manage_tool()
        await manage_tool.ainvoke({
            "action": "create",
            "id": "news-extractor",
            "name": "News Extractor",
            "description": "Extract structured news data from webpages.",
            "content": "# News Extractor",
            "tags": ["news", "web"],
            "executable_code": '''
from langchain_core.tools import tool
from nexagent.skills.base import BaseSkill, SkillMetadata


class NewsExtractorSkill(BaseSkill):
    metadata = SkillMetadata(name="news-extractor", description="Extract news.")

    def get_tools(self):
        @tool("extract_news")
        def extract_news(url: str) -> str:
            """Extract structured news data from a URL."""
            return url

        return [extract_news]
''',
        })

        list_tool = get_list_skills_tool()
        result = await list_tool.ainvoke({"query": "news"})
        payload = json.loads(result)

        assert payload["count"] == 1
        assert payload["skills"][0]["id"] == "news-extractor"
        assert payload["skills"][0]["executable_tools"][0]["name"] == "extract_news"
        assert "structured news" in payload["skills"][0]["executable_tools"][0]["description"]
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_patch_and_history(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        manage_tool = get_skill_manage_tool()
        await manage_tool.ainvoke({
            "action": "create",
            "id": "patchable-skill",
            "name": "Patchable Skill",
            "content": "# Workflow\n\nExtract the title.",
        })

        result = await manage_tool.ainvoke({
            "action": "patch",
            "id": "patchable-skill",
            "find": "Extract the title.",
            "replace": "Extract the title and author.",
            "expected_count": 1,
        })
        payload = json.loads(result)

        assert payload["ok"] is True
        assert "title and author" in (
            workspace / "skills" / "public" / "patchable-skill" / "SKILL.md"
        ).read_text(encoding="utf-8")

        history = json.loads(await manage_tool.ainvoke({"action": "history", "id": "patchable-skill"}))
        assert any(record["action"] == "patch" for record in history["history"])
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_write_and_remove_resource(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        manage_tool = get_skill_manage_tool()
        await manage_tool.ainvoke({
            "action": "create",
            "id": "resource-skill",
            "name": "Resource Skill",
            "content": "# Resource",
        })

        result = await manage_tool.ainvoke({
            "action": "write_file",
            "id": "resource-skill",
            "path": "references/example.md",
            "content": "hello",
        })
        assert json.loads(result)["ok"] is True
        resource = workspace / "skills" / "public" / "resource-skill" / "references" / "example.md"
        assert resource.read_text(encoding="utf-8") == "hello"

        result = await manage_tool.ainvoke({
            "action": "remove_file",
            "id": "resource-skill",
            "path": "references/example.md",
        })
        assert json.loads(result)["ok"] is True
        assert not resource.exists()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_blocks_high_risk_script(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        manage_tool = get_skill_manage_tool()
        await manage_tool.ainvoke({
            "action": "create",
            "id": "safe-skill",
            "name": "Safe Skill",
            "content": "# Safe",
        })

        result = await manage_tool.ainvoke({
            "action": "write_file",
            "id": "safe-skill",
            "path": "scripts/cleanup.py",
            "content": "import shutil\nshutil.rmtree('C:/')\n",
        })

        assert result.startswith("Error:")
        assert "Security scan" in result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
