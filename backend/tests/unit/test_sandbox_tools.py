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
    base_dir: root
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
