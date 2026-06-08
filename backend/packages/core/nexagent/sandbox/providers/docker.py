"""Docker sandbox provider.

The current implementation reuses the local virtual filesystem and executes
commands through Docker only for ``bash``. File operations remain host-side path
translations so the UI can inspect artifacts without container coupling.
"""

from __future__ import annotations

import asyncio
import os
import posixpath
import shlex
import shutil
from pathlib import Path
from typing import NamedTuple

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


class _DockerRunPlan(NamedTuple):
    binds: list[str]
    working_dir: str
    command: str


class DockerSandbox(LocalSandbox):
    async def execute_command(self, command: str, timeout: int = 60) -> str:
        safety_error = _validate_command(command)
        if safety_error:
            _audit(self.thread_id, "bash", {"command": command}, "blocked", safety_error)
            return safety_error

        cwd = self.translator.to_real(".", self.thread_id)
        cwd.mkdir(parents=True, exist_ok=True)
        skills_root = self.translator.to_real(VirtualPathTranslator.SKILLS, self.thread_id)
        skills_root.mkdir(parents=True, exist_ok=True)

        if shutil.which("docker"):
            result = await _run_docker_cli(command, cwd, skills_root, timeout)
        elif _docker_socket_path().exists():
            result = await _run_docker_via_api(command, cwd, skills_root, timeout)
        else:
            result = (
                "Docker sandbox is configured but neither docker CLI nor Docker socket is available. "
                "Install docker CLI in the gateway container or mount /var/run/docker.sock."
            )
        _audit(self.thread_id, "bash", {"command": command, "timeout": timeout}, "ok", result[:1000])
        return result


async def _run_docker_cli(command: str, cwd: Path, skills_root: Path, timeout: int) -> str:
    cfg = get_config().sandbox
    plan = _docker_run_plan(command, cwd, skills_root)
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
    ]
    for bind in plan.binds:
        cmd.extend(["-v", bind])
    cmd.extend(["-w", plan.working_dir, cfg.docker_image, "sh", "-lc", plan.command])
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
    return _format_output(stdout, stderr, proc.returncode or 0, _bash_output_max_chars())


async def _run_docker_via_api(command: str, cwd: Path, skills_root: Path, timeout: int) -> str:
    try:
        import httpx
    except ImportError as exc:
        return f"Docker API client dependency is unavailable: {exc}"

    cfg = get_config().sandbox
    plan = _docker_run_plan(command, cwd, skills_root)
    socket_path = _docker_socket_path()
    host_config: dict[str, object] = {
        "NetworkMode": cfg.docker_network,
        "Binds": plan.binds,
        "AutoRemove": False,
    }
    memory = _docker_memory_bytes(cfg.docker_memory_limit)
    if memory:
        host_config["Memory"] = memory
    if cfg.docker_cpu_quota > 0:
        host_config["CpuQuota"] = cfg.docker_cpu_quota

    payload = {
        "Image": cfg.docker_image,
        "Cmd": ["sh", "-lc", plan.command],
        "WorkingDir": plan.working_dir,
        "Tty": True,
        "AttachStdout": True,
        "AttachStderr": True,
        "HostConfig": host_config,
    }

    container_id = ""
    transport = httpx.AsyncHTTPTransport(uds=str(socket_path))
    async with httpx.AsyncClient(transport=transport, base_url="http://docker") as client:
        try:
            created = await client.post("/containers/create", json=payload)
            if created.status_code >= 400:
                return _docker_api_error("create container", created)
            container_id = str(created.json().get("Id") or "")
            if not container_id:
                return "Docker API create container failed: response did not include a container id."

            started = await client.post(f"/containers/{container_id}/start")
            if started.status_code >= 400:
                return _docker_api_error("start container", started)

            try:
                waited = await asyncio.wait_for(client.post(f"/containers/{container_id}/wait"), timeout=timeout)
            except TimeoutError:
                await client.delete(f"/containers/{container_id}", params={"force": "true"})
                return f"Command timed out after {timeout} seconds."
            if waited.status_code >= 400:
                return _docker_api_error("wait for container", waited)
            status_code = int(waited.json().get("StatusCode") or 0)

            logs = await client.get(
                f"/containers/{container_id}/logs",
                params={"stdout": "true", "stderr": "true"},
            )
            if logs.status_code >= 400:
                return _docker_api_error("read container logs", logs)
            return _format_output(logs.content, b"", status_code, _bash_output_max_chars())
        finally:
            if container_id:
                try:
                    await client.delete(f"/containers/{container_id}", params={"force": "true"})
                except Exception:
                    pass


def _docker_run_plan(command: str, cwd: Path, skills_root: Path) -> _DockerRunPlan:
    host_root = os.environ.get("NEXAGENT_SANDBOX_HOST_ROOT", "").strip()
    container_root = os.environ.get("NEXAGENT_SANDBOX_CONTAINER_ROOT", "").strip()
    if host_root and container_root:
        container_base = Path(container_root).resolve()
        container_cwd = _container_path(cwd, container_base)
        container_skills = _container_path(skills_root, container_base)
        return _DockerRunPlan(
            binds=[f"{Path(host_root).resolve()}:{container_base.as_posix()}"],
            working_dir="/",
            command=_wrap_sandbox_command(command, container_cwd, container_skills),
        )

    return _DockerRunPlan(
        binds=[
            f"{cwd.resolve()}:/workspace",
            f"{skills_root.resolve()}:{VirtualPathTranslator.SKILLS}:ro",
        ],
        working_dir="/workspace",
        command=command,
    )


def _container_path(path: Path, container_base: Path) -> str:
    resolved = path.resolve()
    try:
        suffix = resolved.relative_to(container_base)
    except ValueError:
        return resolved.as_posix()
    return (container_base / suffix).as_posix()


def _wrap_sandbox_command(command: str, workspace: str, skills: str) -> str:
    thread_root = posixpath.dirname(posixpath.dirname(workspace.rstrip("/")))
    uploads = posixpath.join(thread_root, "uploads")
    outputs = posixpath.join(thread_root, "outputs")
    return " && ".join(
        [
            "mkdir -p /mnt/user-data /mnt",
            f"ln -sfn {shlex.quote(skills)} /mnt/skills",
            f"ln -sfn {shlex.quote(workspace)} /mnt/user-data/workspace",
            f"ln -sfn {shlex.quote(uploads)} /mnt/user-data/uploads",
            f"ln -sfn {shlex.quote(outputs)} /mnt/user-data/outputs",
            f"cd {shlex.quote(workspace)}",
            f"sh -lc {shlex.quote(command)}",
        ]
    )


def _docker_socket_path() -> Path:
    return Path(os.environ.get("NEXAGENT_DOCKER_SOCKET", "/var/run/docker.sock"))


def _docker_memory_bytes(value: str) -> int | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    suffix = raw[-1]
    multipliers = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
    if suffix.isdigit():
        digits = raw
        multiplier = 1
    else:
        digits = raw[:-1]
        multiplier = multipliers.get(suffix, 0)
    if not multiplier or not digits.isdigit():
        return None
    return int(digits) * multiplier


def _docker_api_error(action: str, response) -> str:
    try:
        message = response.json().get("message") or response.text
    except Exception:
        message = response.text
    if "No such image" in message:
        image = get_config().sandbox.docker_image
        return f"Docker API {action} failed ({response.status_code}): image '{image}' is not available locally."
    return f"Docker API {action} failed ({response.status_code}): {message}"


class DockerSandboxProvider(LocalSandboxProvider):
    async def acquire(self, thread_id: str) -> DockerSandbox:
        self.translator.ensure_thread_dirs(thread_id)
        _prepare_knowledge_mount(self.translator)
        return DockerSandbox(thread_id, self.translator)
