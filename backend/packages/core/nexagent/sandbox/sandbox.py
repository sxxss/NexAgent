"""Sandbox abstraction with virtual path translation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class VirtualPathTranslator:
    """Translate agent-visible paths to per-thread local paths."""

    WORKSPACE = "/mnt/user-data/workspace"
    UPLOADS = "/mnt/user-data/uploads"
    OUTPUTS = "/mnt/user-data/outputs"
    KNOWLEDGE = "/mnt/knowledge"

    def __init__(self, base_dir: str | Path = ".nexagent") -> None:
        self.base_dir = Path(base_dir)

    def thread_root(self, thread_id: str) -> Path:
        return self.base_dir / "threads" / _safe_id(thread_id)

    def to_real(self, virtual: str | Path, thread_id: str) -> Path:
        value = str(virtual).replace("\\", "/")
        root = self.thread_root(thread_id)
        mappings = {
            self.WORKSPACE: root / "workspace",
            self.UPLOADS: root / "uploads",
            self.OUTPUTS: root / "outputs",
        }
        for prefix, real_root in mappings.items():
            if value == prefix or value.startswith(prefix + "/"):
                suffix = value[len(prefix) :].lstrip("/")
                return _resolve_inside(real_root, suffix)

        if value == "." or not value.startswith("/"):
            return _resolve_inside(root / "workspace", value)

        if value.startswith(self.KNOWLEDGE + "/"):
            suffix = value[len(self.KNOWLEDGE) :].lstrip("/")
            return _resolve_inside(self.base_dir / "knowledge", suffix)

        raise ValueError(f"Path is outside sandbox virtual roots: {virtual}")

    def to_virtual(self, real: str | Path, thread_id: str) -> str:
        path = Path(real).resolve()
        root = self.thread_root(thread_id).resolve()
        mappings = {
            (root / "workspace").resolve(): self.WORKSPACE,
            (root / "uploads").resolve(): self.UPLOADS,
            (root / "outputs").resolve(): self.OUTPUTS,
            (self.base_dir / "knowledge").resolve(): self.KNOWLEDGE,
        }
        for real_root, virtual_root in mappings.items():
            try:
                suffix = path.relative_to(real_root)
                return f"{virtual_root}/{suffix.as_posix()}".rstrip("/")
            except ValueError:
                continue
        raise ValueError(f"Real path is outside sandbox roots: {real}")

    def ensure_thread_dirs(self, thread_id: str) -> None:
        root = self.thread_root(thread_id)
        for name in ("workspace", "uploads", "outputs"):
            (root / name).mkdir(parents=True, exist_ok=True)


class Sandbox(ABC):
    """Abstract sandbox operations."""

    def __init__(self, thread_id: str, translator: VirtualPathTranslator) -> None:
        self.thread_id = thread_id
        self.translator = translator

    @abstractmethod
    async def execute_command(self, command: str, timeout: int = 60) -> str: ...

    @abstractmethod
    async def list_dir(self, path: str = ".", max_depth: int = 2) -> str: ...

    @abstractmethod
    async def read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str: ...

    @abstractmethod
    async def write_file(self, path: str, content: str, append: bool = False) -> str: ...

    @abstractmethod
    async def str_replace(self, path: str, old_str: str, new_str: str) -> str: ...

    @abstractmethod
    async def present_artifacts(self) -> list[str]: ...


class SandboxProvider(ABC):
    """Acquire and release sandboxes for an agent thread."""

    @abstractmethod
    async def acquire(self, thread_id: str) -> Sandbox: ...

    @abstractmethod
    async def release(self, sandbox: Sandbox) -> None: ...


def get_sandbox_provider() -> SandboxProvider:
    from nexagent.config import get_config
    from nexagent.sandbox.providers.docker import DockerSandboxProvider
    from nexagent.sandbox.providers.local import LocalSandboxProvider

    cfg = get_config().sandbox
    if cfg.provider == "docker":
        return DockerSandboxProvider()
    return LocalSandboxProvider(base_dir=cfg.base_dir)


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value or "default")


def _resolve_inside(root: Path, suffix: str) -> Path:
    root = root.resolve()
    path = (root / suffix).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"Path escapes sandbox root: {suffix}")
    return path
