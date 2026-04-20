"""Docker sandbox provider.

The current implementation reuses the local virtual filesystem and executes
commands through Docker only for ``bash``. File operations remain host-side path
translations so the UI can inspect artifacts without container coupling.
"""

from __future__ import annotations

import asyncio
import shutil

from nexagent.config import get_config
from nexagent.sandbox.providers.local import LocalSandbox, LocalSandboxProvider, _format_output


class DockerSandbox(LocalSandbox):
    async def execute_command(self, command: str, timeout: int = 60) -> str:
        if not shutil.which("docker"):
            return "Docker sandbox is configured but docker is not available on PATH."

        cfg = get_config().sandbox
        cwd = self.translator.to_real(".", self.thread_id)
        cwd.mkdir(parents=True, exist_ok=True)
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
            return f"Command timed out after {timeout} seconds."
        return _format_output(stdout, stderr, proc.returncode or 0)


class DockerSandboxProvider(LocalSandboxProvider):
    async def acquire(self, thread_id: str) -> DockerSandbox:
        self.translator.ensure_thread_dirs(thread_id)
        return DockerSandbox(thread_id, self.translator)
