from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.mark.unit
def test_docker_sandbox_builds_host_root_bind_plan(monkeypatch):
    from nexagent.sandbox.providers import docker as docker_provider

    monkeypatch.setenv("NEXAGENT_SANDBOX_HOST_ROOT", "/host/nexagent/.nexagent")
    monkeypatch.setenv("NEXAGENT_SANDBOX_CONTAINER_ROOT", "/app/.nexagent")

    plan = docker_provider._docker_run_plan(
        "printf ok",
        Path("/app/.nexagent/threads/t/workspace"),
        Path("/app/.nexagent/threads/t/skills"),
    )

    assert plan.binds == ["/host/nexagent/.nexagent:/app/.nexagent"]
    assert plan.working_dir == "/"
    assert "ln -sfn /app/.nexagent/threads/t/skills /mnt/skills" in plan.command
    assert "cd /app/.nexagent/threads/t/workspace" in plan.command
    assert "sh -lc 'printf ok'" in plan.command


@pytest.mark.unit
@pytest.mark.asyncio
async def test_docker_sandbox_uses_engine_api_when_cli_is_missing(monkeypatch):
    from nexagent.config import reset_config_cache
    from nexagent.sandbox.providers import docker as docker_provider

    base = Path(__file__).resolve().parents[2] / ".test-artifacts" / f"docker-sandbox-{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NEXAGENT_CONFIG_PATH", str(base / "config.yaml"))
    monkeypatch.setenv("NEXAGENT_DOCKER_SOCKET", str(base / "docker.sock"))
    (base / "docker.sock").touch()
    (base / "config.yaml").write_text(
        f"""
sandbox:
  enabled: true
  provider: docker
  local:
    base_dir: {base / "root"}
  docker:
    image: python:3.12-slim
    memory_limit: 512m
    cpu_quota: 50000
    network: none
  audit_enabled: false
  allow_bash: true
  blocked_commands: []
  max_output_chars: 8000
""",
        encoding="utf-8",
    )
    reset_config_cache()
    monkeypatch.setattr(docker_provider.shutil, "which", lambda name: None)

    async def fake_run_via_api(command, cwd, skills_root, timeout):
        return f"api:{command}:{cwd.name}:{skills_root.name}:{timeout}"

    monkeypatch.setattr(docker_provider, "_run_docker_via_api", fake_run_via_api, raising=False)

    try:
        sandbox = await docker_provider.DockerSandboxProvider(base / "root").acquire("thread")
        result = await sandbox.execute_command("echo ok", timeout=7)
    finally:
        reset_config_cache()
        shutil.rmtree(base, ignore_errors=True)

    assert result == "api:echo ok:workspace:skills:7"
