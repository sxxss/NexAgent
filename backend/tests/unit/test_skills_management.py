from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException


def _skills_dir(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / ".test-artifacts" / name / uuid.uuid4().hex


@pytest.mark.unit
def test_skill_loader_parses_metadata_hash_and_prompt(monkeypatch):
    from nexagent.skills.loader import SkillLoader

    work_dir = _skills_dir("skills-loader")
    skill_dir = work_dir / "public" / "csv-profiler"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
id: csv-profiler
name: CSV Profiler
description: Profile CSV files
version: 1.2.3
tags: [data, csv]
required_mcp_ids: [filesystem]
required_tools: [execute_python]
---

# CSV Profiler

Use this skill for tabular data profiling.
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(work_dir))

    try:
        loader = SkillLoader()
        skill = loader.load("csv-profiler")

        assert skill is not None
        assert skill.id == "csv-profiler"
        assert skill.tags == ["data", "csv"]
        assert skill.required_mcp_ids == ["filesystem"]
        assert skill.required_tools == ["execute_python"]
        assert len(skill.content_hash) == 64
        assert skill.validation_issues == []
        prompt = loader.to_system_prompt_blocks([skill])
        assert "<id>csv-profiler</id>" in prompt
        assert "<location>/mnt/skills/csv-profiler/SKILL.md</location>" in prompt
        assert "Use this skill for tabular data profiling." not in prompt
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_skill_loader_loads_supporting_resources(monkeypatch):
    from nexagent.skills.loader import SkillLoader

    work_dir = _skills_dir("skills-resources")
    skill_dir = work_dir / "public" / "analyst"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
id: analyst
name: Analyst
description: Analyze data
version: 0.1.0
---

# Analyst

Use the packaged rubric before answering.
""",
        encoding="utf-8",
    )
    (skill_dir / "rubric.md").write_text("# Rubric\n\nCheck sources and assumptions.", encoding="utf-8")
    (skill_dir / "assets.bin").write_bytes(b"\x00\x01")
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(work_dir))

    try:
        loader = SkillLoader()
        skill = loader.load("analyst")

        assert skill is not None
        assert {item["path"] for item in skill.files} == {"SKILL.md", "assets.bin", "rubric.md"}
        assert skill.resources == [{"path": "rubric.md", "content": "# Rubric\n\nCheck sources and assumptions."}]
        prompt = loader.to_system_prompt_blocks([skill])
        assert "<location>/mnt/skills/analyst/SKILL.md</location>" in prompt
        assert "rubric.md" not in prompt
        assert "Check sources and assumptions." not in prompt
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_skill_loader_reports_invalid_metadata(monkeypatch):
    from nexagent.skills.loader import SkillLoader

    work_dir = _skills_dir("skills-invalid")
    skill_dir = work_dir / "public" / "bad skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("---\nversion: dev\n---\n", encoding="utf-8")
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(work_dir))

    try:
        skill = SkillLoader().load("bad skill")
        assert skill is not None
        codes = {issue.code for issue in skill.validation_issues}
        assert "invalid_id" in codes
        assert "invalid_version" in codes
        assert "empty_prompt" in codes
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_install_skill_dir_preserves_zip_resources(monkeypatch):
    from nexagent.skills.loader import SkillLoader

    from app.gateway.routers import skills as skills_router

    work_dir = _skills_dir("skills-zip")
    source_dir = work_dir / "source" / "packaged-skill"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "SKILL.md").write_text(
        "---\nid: packaged-skill\nname: Packaged Skill\nversion: 0.1.0\n---\n\n# Packaged\n",
        encoding="utf-8",
    )
    (source_dir / "prompts").mkdir()
    (source_dir / "prompts" / "system.md").write_text("Use a strict checklist.", encoding="utf-8")
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(work_dir / "installed"))

    try:
        loader = SkillLoader()
        target = skills_router._install_skill_dir(source_dir, loader.public_dir, "packaged-skill", force=False)
        assert (target / "prompts" / "system.md").exists()

        skill = loader.load("packaged-skill")
        assert skill is not None
        assert any(item["path"] == "prompts/system.md" for item in skill.files)
        assert skill.resources[0]["content"] == "Use a strict checklist."
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_remote_skill_candidate_listing_supports_multiple_skills():
    from app.gateway.routers import skills as skills_router

    work_dir = _skills_dir("skills-remote-list")
    try:
        first = work_dir / "repo-main" / "skills" / "public" / "one"
        second = work_dir / "repo-main" / "skills" / "public" / "two"
        first.mkdir(parents=True, exist_ok=True)
        second.mkdir(parents=True, exist_ok=True)
        (first / "SKILL.md").write_text(
            "---\nid: one\nname: One\nversion: 0.1.0\ntags: [alpha]\n---\n\n# One\n",
            encoding="utf-8",
        )
        (second / "SKILL.md").write_text(
            "---\nid: two\nname: Two\ndescription: Second skill\nversion: 0.1.0\n---\n\n# Two\n",
            encoding="utf-8",
        )

        candidates = skills_router._list_skill_candidates(work_dir)

        assert [item["id"] for item in candidates] == ["one", "two"]
        assert candidates[0]["subdir"] == "repo-main/skills/public/one"
        assert candidates[0]["tags"] == ["alpha"]
        assert candidates[1]["description"] == "Second skill"
        assert candidates[1]["content_hash"]
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_remote_skill_zip_listing_ignores_unrelated_repo_files():
    from app.gateway.routers import skills as skills_router

    work_dir = _skills_dir("skills-large-remote-zip")
    archive = work_dir / "repo.zip"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive, "w") as zf:
            for index in range(390):
                zf.writestr(f"repo-main/docs/file-{index}.txt", "not a skill")
            zf.writestr(
                "repo-main/skills/public/research/SKILL.md",
                "---\nid: research\nname: Research\nversion: 0.1.0\n---\n\n# Research\n",
            )
            zf.writestr("repo-main/skills/public/research/prompts/system.md", "Use sources.")

        candidates = skills_router._list_skill_candidates_from_zip(archive.read_bytes())
        assert [item["id"] for item in candidates] == ["research"]
        assert candidates[0]["subdir"] == "repo-main/skills/public/research"

        target = skills_router._extract_skill_zip_candidate(
            archive.read_bytes(),
            work_dir / "tmp",
            "repo-main/skills/public/research",
            None,
        )
        assert (target / "SKILL.md").exists()
        assert (target / "prompts" / "system.md").exists()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_skill_zip_rejects_blocked_file_types():
    from app.gateway.routers import skills as skills_router

    work_dir = _skills_dir("skills-blocked-zip")
    archive = work_dir / "blocked.zip"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("bad/SKILL.md", "---\nid: bad\nname: Bad\n---\n\n# Bad\n")
            zf.writestr("bad/install.ps1", "Write-Host bad")

        (work_dir / "tmp").mkdir()
        with pytest.raises(HTTPException) as exc_info:
            skills_router._extract_skill_zip(archive.read_bytes(), work_dir / "tmp")

        assert exc_info.value.status_code == 400
        assert "Blocked file type" in str(exc_info.value.detail)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_custom_skill_install_conflict_and_force(monkeypatch):
    from app.gateway.routers.skills import SkillCustomRequest, custom

    work_dir = _skills_dir("skills-custom")
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(work_dir))
    body = SkillCustomRequest(
        id="writer",
        name="Writer",
        description="Write structured content",
        version="0.1.0",
        tags=["writing"],
        content="# Writer\n\nUse concise prose.",
    )

    try:
        created = await custom(body)
        assert created["id"] == "writer"
        assert created["content_hash"]

        with pytest.raises(HTTPException) as exc_info:
            await custom(body)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["content_hash"]

        forced = await custom(body.model_copy(update={"force": True, "content": "# Writer\n\nUpdated."}))
        assert forced["id"] == "writer"
        assert forced["content_hash"] != created["content_hash"]
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_missing_tool_dependency_reports_error(monkeypatch):
    from nexagent.skills.validation import missing_tool_issues

    work_dir = _skills_dir("skills-deps")
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(work_dir))

    try:
        issues = missing_tool_issues(["execute_python", "missing_tool"])
        assert [issue.code for issue in issues] == ["missing_tool_dependency"]
        assert "missing_tool" in issues[0].message
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_plan_adds_skill_dependencies(monkeypatch):
    from nexagent.skills.loader import SkillLoader
    from nexagent.skills.validation import resolve_runtime_plan

    work_dir = _skills_dir("skills-runtime")
    skill_dir = work_dir / "public" / "writer"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
id: writer
name: Writer
description: Write with web context
version: 0.1.0
required_tools: [web_fetch]
---

# Writer
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(work_dir))

    try:
        loader = SkillLoader()
        skill = loader.load("writer")
        assert skill is not None
        plan = await resolve_runtime_plan([skill], loader=loader, selected_tool_names=["knowledge_search"])
        assert plan.required_tools == ["knowledge_search", "web_fetch"]
        assert not plan.has_errors
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_plan_blocks_disabled_subagent_dependency(monkeypatch):
    from nexagent.skills.loader import SkillLoader
    from nexagent.skills.validation import resolve_runtime_plan

    work_dir = _skills_dir("skills-runtime-subagent")
    skill_dir = work_dir / "public" / "delegate"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
id: delegate
name: Delegate
description: Delegate tasks
version: 0.1.0
required_tools: [delegate_subagents]
---

# Delegate
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(work_dir))

    try:
        loader = SkillLoader()
        skill = loader.load("delegate")
        assert skill is not None
        plan = await resolve_runtime_plan([skill], loader=loader, allow_subagents=False)
        assert plan.has_errors
        assert "subagent_dependency_disabled" in {issue.code for issue in plan.issues}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_skill_prompt_injection_has_stable_order_and_budget(monkeypatch):
    from nexagent.skills.loader import SkillLoader

    work_dir = _skills_dir("skills-prompt-budget")
    for skill_id in ("b-skill", "a-skill"):
        skill_dir = work_dir / "public" / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            (
                f"---\nid: {skill_id}\nname: {skill_id}\n"
                f"description: {skill_id} description\nversion: 0.1.0\n---\n\n"
                + ("x" * 200)
            ),
            encoding="utf-8",
        )
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(work_dir))

    try:
        loader = SkillLoader()
        skills = loader.load_selected(["b-skill", "a-skill"])
        prompt = loader.to_system_prompt_blocks(skills, max_chars_per_skill=20, max_total_chars=80)
        assert prompt.index("<id>a-skill</id>") < prompt.index("<id>b-skill</id>")
        assert "x" * 20 not in prompt
        assert "skills/<skill-id>/scripts/example.py" in prompt
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
