"""Local filesystem sandbox provider for development."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from nexagent.sandbox.sandbox import Sandbox, SandboxProvider, VirtualPathTranslator


class LocalSandbox(Sandbox):
    """Per-thread local sandbox rooted under .nexagent/threads/{thread_id}."""

    async def execute_command(self, command: str, timeout: int = 60) -> str:
        safety_error = _validate_command(command)
        if safety_error:
            _audit(self.thread_id, "bash", {"command": command}, "blocked", safety_error)
            return safety_error
        cwd = self.translator.to_real(".", self.thread_id)
        cwd.mkdir(parents=True, exist_ok=True)
        try:
            completed = await asyncio.to_thread(_run_command, command, cwd, timeout)
        except subprocess.TimeoutExpired:
            result = f"Command timed out after {timeout} seconds."
            _audit(self.thread_id, "bash", {"command": command, "timeout": timeout}, "timeout", result)
            return result
        except FileNotFoundError as exc:
            result = f"Shell not found: {exc}"
            _audit(self.thread_id, "bash", {"command": command, "timeout": timeout}, "error", result)
            return result
        result = _format_output(completed.stdout, completed.stderr, completed.returncode, _bash_output_max_chars())
        _audit(self.thread_id, "bash", {"command": command, "timeout": timeout}, "ok", result[:1000])
        return result

    async def list_dir(self, path: str = ".", max_depth: int = 2) -> str:
        root = self.translator.to_real(path, self.thread_id)
        if not root.exists():
            return f"Path not found: {path}"
        lines: list[str] = []
        self._walk(root, root, lines, max_depth=max(0, max_depth), depth=0)
        result = "\n".join(lines) if lines else "(empty)"
        _audit(self.thread_id, "ls", {"path": path, "max_depth": max_depth}, "ok", "")
        return result

    def _walk(self, root: Path, current: Path, lines: list[str], max_depth: int, depth: int) -> None:
        if depth > max_depth:
            return
        prefix = "  " * depth
        for child in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            rel = child.relative_to(root).as_posix()
            lines.append(f"{prefix}{rel}{'/' if child.is_dir() else ''}")
            if child.is_dir() and depth < max_depth:
                self._walk(root, child, lines, max_depth=max_depth, depth=depth + 1)

    async def read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        real = self.translator.to_real(path, self.thread_id)
        text = real.read_text(encoding="utf-8", errors="replace")
        if start_line is None and end_line is None:
            _audit(self.thread_id, "read_file", {"path": path}, "ok", f"{len(text)} chars")
            return text
        lines = text.splitlines()
        start = max((start_line or 1) - 1, 0)
        end = end_line if end_line is not None else len(lines)
        result = "\n".join(lines[start:end])
        _audit(self.thread_id, "read_file", {"path": path, "start_line": start_line, "end_line": end_line}, "ok", "")
        return result

    async def write_file(self, path: str, content: str, append: bool = False) -> str:
        if _is_runtime_skill_path(path):
            return (
                "Skill runtime files are read-only. Update installed Skills through the Skill manager, "
                "not sandbox file tools."
            )
        real = self.translator.to_real(path, self.thread_id)
        real.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with real.open(mode, encoding="utf-8") as handle:
            handle.write(content)
        result = f"Wrote {len(content)} characters to {self.translator.to_virtual(real, self.thread_id)}"
        _audit(self.thread_id, "write_file", {"path": path, "append": append, "chars": len(content)}, "ok", result)
        return result

    async def str_replace(self, path: str, old_str: str, new_str: str) -> str:
        if _is_runtime_skill_path(path):
            return (
                "Skill runtime files are read-only. Update installed Skills through the Skill manager, "
                "not sandbox file tools."
            )
        real = self.translator.to_real(path, self.thread_id)
        text = real.read_text(encoding="utf-8", errors="replace")
        count = text.count(old_str)
        if count == 0:
            return "No replacement made: old_str was not found."
        if count > 1:
            return f"No replacement made: old_str matched {count} times. Provide a more specific string."
        real.write_text(text.replace(old_str, new_str), encoding="utf-8")
        result = f"Replaced text in {self.translator.to_virtual(real, self.thread_id)}"
        _audit(self.thread_id, "str_replace", {"path": path}, "ok", result)
        return result

    async def present_artifacts(self) -> list[str]:
        outputs = self.translator.to_real("/mnt/user-data/outputs", self.thread_id)
        if not outputs.exists():
            return []
        artifacts = [
            self.translator.to_virtual(path, self.thread_id)
            for path in sorted(outputs.rglob("*"))
            if path.is_file()
        ]
        _audit(self.thread_id, "present_artifacts", {}, "ok", f"{len(artifacts)} artifacts")
        return artifacts


class LocalSandboxProvider(SandboxProvider):
    def __init__(self, base_dir: str | Path = ".nexagent") -> None:
        self.translator = VirtualPathTranslator(base_dir)

    async def acquire(self, thread_id: str) -> Sandbox:
        self.translator.ensure_thread_dirs(thread_id)
        _prepare_knowledge_mount(self.translator)
        return LocalSandbox(thread_id, self.translator)

    async def release(self, sandbox: Sandbox) -> None:
        return None


def _run_command(command: str, cwd: Path, timeout: int) -> subprocess.CompletedProcess[bytes]:
    args = _shell_args(command)
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        timeout=timeout,
        check=False,
        shell=False,
    )


def _shell_args(command: str) -> list[str]:
    if os.name == "nt":
        shell = _first_available_shell(
            (
                "pwsh",
                "pwsh.exe",
                "powershell",
                "powershell.exe",
                "cmd",
                "cmd.exe",
            )
        )
        name = Path(shell).name.lower()
        if name in {"pwsh", "pwsh.exe", "powershell", "powershell.exe"}:
            return [shell, "-NoProfile", "-Command", command]
        return [shell, "/c", command]

    shell = _first_available_shell(("/bin/sh", "sh"))
    return [shell, "-lc", command]


def _first_available_shell(candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if os.path.isabs(candidate):
            if Path(candidate).is_file():
                return candidate
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FileNotFoundError(", ".join(candidates))


def _format_output(stdout: bytes | str | None, stderr: bytes | str | None, returncode: int, max_chars: int) -> str:
    out = _decode_output(stdout).strip()
    err = _decode_output(stderr).strip()
    parts = []
    if out:
        parts.append(out)
    if err:
        parts.append(f"[stderr]\n{err}")
    if not parts:
        parts.append(f"(Command exited {returncode} with no output)")
    result = "\n".join(parts)
    return _middle_truncate(result, max_chars)


def _decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _middle_truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker_template = "\n... [middle truncated: {skipped} chars skipped] ...\n"
    keep = max(0, max_chars - len(marker_template.format(skipped=len(text))))
    marker = marker_template.format(skipped=len(text) - keep)
    head = keep // 2
    tail = keep - head
    return f"{text[:head]}{marker}{text[-tail:] if tail else ''}"


def _bash_output_max_chars() -> int:
    try:
        from nexagent.config import get_config

        return int(get_config().sandbox.max_output_chars)
    except Exception:
        return 8000


def _validate_command(command: str) -> str | None:
    from nexagent.config import get_config

    cfg = get_config().sandbox
    if not cfg.allow_bash:
        return "Bash execution is disabled by sandbox.allow_bash=false."
    lowered = command.lower()
    for blocked in cfg.blocked_commands:
        if blocked and blocked.strip().lower() in lowered:
            return f"Command blocked by sandbox policy: {blocked}"
    return None


def _is_runtime_skill_path(path: str) -> bool:
    value = str(path).replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    return (
        value == "skills"
        or value.startswith("skills/")
        or value == "/mnt/skills"
        or value.startswith("/mnt/skills/")
        or value == "/mnt/user-data/workspace/skills"
        or value.startswith("/mnt/user-data/workspace/skills/")
    )


def _audit(thread_id: str, action: str, input_data: dict, status: str, message: str) -> None:
    try:
        from nexagent.config import get_config

        cfg = get_config().sandbox
        if not cfg.audit_enabled:
            return
        path = Path(cfg.audit_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "time": datetime.now(UTC).isoformat(),
            "thread_id": thread_id,
            "action": action,
            "input": input_data,
            "status": status,
            "message": message,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        return


def _prepare_knowledge_mount(translator: VirtualPathTranslator) -> None:
    """Expose parsed KB files under /mnt/knowledge when local paths exist."""
    import shutil

    try:
        data_root = Path(os.environ.get("NEXAGENT_DATA_DIR", str(Path.home() / ".nexagent"))) / "knowledge"
        mount_root = translator.base_dir / "knowledge"
        mount_root.mkdir(parents=True, exist_ok=True)
        if not data_root.exists():
            return
        for parsed_dir in data_root.glob("*/*/parsed"):
            kb_id = parsed_dir.parent.name
            target = mount_root / kb_id
            target.mkdir(parents=True, exist_ok=True)
            for file in parsed_dir.glob("*"):
                if file.is_file():
                    dest = target / file.name
                    if not dest.exists() or file.stat().st_mtime > dest.stat().st_mtime:
                        shutil.copyfile(file, dest)
    except Exception:
        return
