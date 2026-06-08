"""Docker sandbox provider.

The current implementation reuses the local virtual filesystem and executes
commands through Docker only for ``bash``. File operations remain host-side path
translations so the UI can inspect artifacts without container coupling.
"""

from __future__ import annotations

import asyncio
import shutil

from nexagent.config import get_config
from nexagent.sandbox.providers.local import (
    LocalSandbox,
    LocalSandboxProvider,
    _audit,
    _bash_output_max_chars,
    _format_output,
    _prepare_knowledge_mount,
    _validate_command,
)
from nexagent.sandbox.sandbox import VirtualPathTranslator


class DockerSandbox(LocalSandbox):
    async def execute_command(self, command: str, timeout: int = 60) -> str:
        safety_error = _validate_command(command)
        if safety_error:
            _audit(self.thread_id, "bash", {"command": command}, "blocked", safety_error)
            return safety_error
        if not shutil.which("docker"):
            return "Docker sandbox is configured but docker is not available on PATH."

        cfg = get_config().sandbox
        cwd = self.translator.to_real(".", self.thread_id)
        cwd.mkdir(parents=True, exist_ok=True)
        skills_root = self.translator.to_real(VirtualPathTranslator.SKILLS, self.thread_id)
        skills_root.mkdir(parents=True, exist_ok=True)
        cmd = [
            "docker",
            "run",
            "--rm",
            "--network",
            cfg.docker_network,
            "--memory",
            cfg.docker_memory_limit,
            "--cpu-quota",
            str(cfg.docker_cpu_quota),
            "-v",
            f"{cwd.resolve()}:/workspace",
            "-v",
            f"{skills_root.resolve()}:{VirtualPathTranslator.SKILLS}:ro",
            "-w",
            "/workspace",
            cfg.docker_image,
            "sh",
            "-lc",
            command,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            result = f"Command timed out after {timeout} seconds."
            _audit(self.thread_id, "bash", {"command": command, "timeout": timeout}, "timeout", result)
            return result
        result = _format_output(stdout, stderr, proc.returncode or 0, _bash_output_max_chars())
        _audit(self.thread_id, "bash", {"command": command, "timeout": timeout}, "ok", result[:1000])
        return result


class DockerSandboxProvider(LocalSandboxProvider):
    async def acquire(self, thread_id: str) -> DockerSandbox:
        self.translator.ensure_thread_dirs(thread_id)
        _prepare_knowledge_mount(self.translator)
        return DockerSandbox(thread_id, self.translator)
