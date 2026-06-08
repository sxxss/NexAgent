from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.mark.unit
async def test_local_sandbox_blocks_configured_dangerous_command(monkeypatch):
    from nexagent.config import reset_config_cache
    from nexagent.sandbox.providers.local import LocalSandboxProvider

    base = Path(__file__).resolve().parents[2] / ".test-artifacts" / f"sandbox-tools-{uuid.uuid4().hex}"
    monkeypatch.setenv("NEXAGENT_CONFIG_PATH", str(base / "config.yaml"))
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.yaml").write_text(
        """
sandbox:
  enabled: true
  provider: local
  local:
    base_dir: .test-artifacts/sandbox-tools/root
  audit_enabled: false
  allow_bash: true
  blocked_commands:
    - forbidden
""",
        encoding="utf-8",
    )
    reset_config_cache()

    try:
        sandbox = await LocalSandboxProvider(base / "root").acquire("thread")
        result = await sandbox.execute_command("echo forbidden")
        artifacts = await sandbox.present_artifacts()
    finally:
        reset_config_cache()
        shutil.rmtree(base, ignore_errors=True)

    assert "blocked" in result.lower()
    assert artifacts == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_sandbox_bash_uses_threaded_subprocess(monkeypatch):
    from nexagent.config import reset_config_cache
    from nexagent.sandbox.providers.local import LocalSandboxProvider

    base = Path(__file__).resolve().parents[2] / ".test-artifacts" / f"sandbox-tools-{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXAGENT_CONFIG_PATH", str(base / "config.yaml"))
    (base / "config.yaml").write_text(
        """
sandbox:
  enabled: true
  provider: local
  local:
    base_dir: {base / "root"}
  audit_enabled: false
  allow_bash: true
  blocked_commands: []
  max_output_chars: 8000
""",
        encoding="utf-8",
    )
    reset_config_cache()

    async def _should_not_be_used(*args, **kwargs):
        raise AssertionError("asyncio.create_subprocess_exec should not be used by LocalSandbox")

    monkeypatch.setattr("asyncio.create_subprocess_exec", _should_not_be_used)

    try:
        sandbox = await LocalSandboxProvider(base / "root").acquire("thread")
        result = await sandbox.execute_command("echo nexagent-ok")
    finally:
        reset_config_cache()
        shutil.rmtree(base, ignore_errors=True)

    assert "nexagent-ok" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_selected_skill_scripts_execute_from_standard_runtime_path(monkeypatch):
    from nexagent.config import reset_config_cache
    from nexagent.sandbox.providers.local import LocalSandboxProvider
    from nexagent.skills.loader import SkillLoader
    from nexagent.skills.runtime import prepare_skill_runtime

    base = Path(__file__).resolve().parents[2] / ".test-artifacts" / f"sandbox-skills-{uuid.uuid4().hex}"
    skills_root = base / "skills"
    skill_dir = skills_root / "public" / "script-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nid: script-skill\nname: Script Skill\ndescription: Run a bundled script.\n---\n\n# Script Skill\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "run.py").write_text("print('skill-script-ok')\n", encoding="utf-8")
    monkeypatch.setenv("NEXAGENT_SKILLS_DIR", str(skills_root))
    monkeypatch.setenv("NEXAGENT_CONFIG_PATH", str(base / "config.yaml"))
    (base / "config.yaml").write_text(
        f"""
sandbox:
  enabled: true
  provider: local
  local:
    base_dir: {base / "root"}
  audit_enabled: false
  allow_bash: true
  blocked_commands: []
""",
        encoding="utf-8",
    )
    reset_config_cache()

    try:
        skill = SkillLoader().load("script-skill")
        assert skill is not None
        prepare_skill_runtime("thread", [skill])
        sandbox = await LocalSandboxProvider(base / "root").acquire("thread")

        skill_md = await sandbox.read_file("/mnt/skills/script-skill/SKILL.md")
        output = await sandbox.execute_command("python3 /mnt/skills/script-skill/scripts/run.py")
        write_result = await sandbox.write_file("/mnt/skills/script-skill/SKILL.md", "changed")
    finally:
        reset_config_cache()
        shutil.rmtree(base, ignore_errors=True)

    assert "# Script Skill" in skill_md
    assert "skill-script-ok" in output
    assert "read-only" in write_result
