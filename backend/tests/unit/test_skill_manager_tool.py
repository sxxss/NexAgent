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
        assert (workspace / "skills" / "custom" / "web-extractor" / "SKILL.md").exists()
        assert (workspace / "skills" / "custom" / "web-extractor" / "references" / "template.md").exists()
        loaded = loader_cls().load("web-extractor")
        assert loaded is not None
        assert loaded.description == "Extract structured data from web pages."
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_create_writes_script_resource(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        tool = get_skill_manage_tool()
        result = await tool.ainvoke({
            "action": "create",
            "id": "echo-skill",
            "name": "Echo Skill",
            "content": "# Echo\n\nRun scripts/echo.py for echoing.",
            "files": [{"path": "scripts/echo.py", "content": "print('echo')\n"}],
        })

        payload = json.loads(result)
        assert payload["ok"] is True
        assert payload["storage"] == "managed"
        assert "path" not in payload
        assert "executable" not in payload
        assert any(item["path"] == "scripts/echo.py" and item["kind"] == "script" for item in payload["files"])
        assert (workspace / "skills" / "custom" / "echo-skill" / "scripts" / "echo.py").exists()
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
            "files": [
                {"path": "references/example.md", "content": "example content"},
                {"path": "scripts/example.py", "content": "print('example')\n"},
            ],
        })

        read_tool = get_read_skill_tool()
        result = await read_tool.ainvoke({"id": "reader-skill"})
        payload = json.loads(result)

        assert payload["id"] == "reader-skill"
        assert payload["storage"] == "managed"
        assert "path" not in payload
        assert "executable_tools" not in payload
        assert any(item["path"] == "SKILL.md" for item in payload["contents"])
        assert not any(item["path"] == "references/example.md" for item in payload["contents"])

        result = await read_tool.ainvoke({"id": "reader-skill", "path": "scripts/example.py"})
        payload = json.loads(result)
        assert payload["contents"][0]["path"] == "scripts/example.py"
        assert "print('example')" in payload["contents"][0]["content"]

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
        assert (workspace / "skills" / "custom" / "preserve-skill" / "references" / "example.md").read_text(
            encoding="utf-8"
        ) == "keep me"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_edit_discards_legacy_root_skill_py(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        root = workspace / "skills" / "public" / "legacy-python"
        root.mkdir(parents=True)
        (root / "SKILL.md").write_text(
            "---\nid: legacy-python\nname: Legacy Python\ndescription: Legacy file.\n---\n\n# Old\n",
            encoding="utf-8",
        )
        (root / "skill.py").write_text("print('legacy')\n", encoding="utf-8")

        tool = get_skill_manage_tool()
        result = await tool.ainvoke({
            "action": "edit",
            "id": "legacy-python",
            "name": "Legacy Python",
            "description": "Updated.",
            "content": "# Updated",
        })

        payload = json.loads(result)
        assert payload["ok"] is True
        assert "warning" not in payload
        assert not (root / "skill.py").exists()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skill_manage_rejects_root_skill_py_resource(monkeypatch):
    from nexagent.tools.builtin.skill_manager import get_skill_manage_tool

    workspace = _workspace()
    _patch_loader(monkeypatch, workspace)

    try:
        tool = get_skill_manage_tool()
        result = await tool.ainvoke({
            "action": "create",
            "id": "legacy-entry",
            "name": "Legacy Entry",
            "content": "# Legacy Entry",
            "files": [{"path": "skill.py", "content": "def get_tools(): return []\n"}],
        })

        assert result.startswith("Error:")
        assert "Root skill.py is not supported" in result
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
            "files": [{"path": "scripts/extract_news.py", "content": "print('news')\n"}],
        })

        list_tool = get_list_skills_tool()
        result = await list_tool.ainvoke({"query": "news"})
        payload = json.loads(result)

        assert payload["count"] == 1
        assert payload["skills"][0]["id"] == "news-extractor"
        assert "executable_tools" not in payload["skills"][0]
        assert payload["skills"][0]["tags"] == ["news", "web"]
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
            workspace / "skills" / "custom" / "patchable-skill" / "SKILL.md"
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
        resource = workspace / "skills" / "custom" / "resource-skill" / "references" / "example.md"
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
