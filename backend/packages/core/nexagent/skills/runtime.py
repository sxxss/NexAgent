"""Runtime preparation for standard progressive Skills."""

from __future__ import annotations

import shutil
import stat
from collections.abc import Callable
from pathlib import Path

from nexagent.skills.loader import Skill


def prepare_skill_runtime(thread_id: str, skills: list[Skill]) -> None:
    """Expose selected Skills in the per-thread sandbox namespace.

    Skills are exposed under ``/mnt/skills/<id>`` via
    ``VirtualPathTranslator.SKILLS``. File tools read that virtual path, and
    sandbox command providers make the same path executable for bundled
    scripts.
    """
    from nexagent.config import get_config
    from nexagent.sandbox.sandbox import VirtualPathTranslator

    translator = VirtualPathTranslator(get_config().sandbox.base_dir)
    thread_root = translator.thread_root(thread_id)
    selected = {skill.id: skill.path.parent.resolve() for skill in skills}
    _sync_root(thread_root / "skills", selected)
    _remove_legacy_workspace_mirror(thread_root / "workspace" / "skills")


def _sync_root(target_root: Path, selected: dict[str, Path]) -> None:
    if target_root.exists():
        _make_writable(target_root)
    target_root.mkdir(parents=True, exist_ok=True)

    for child in list(target_root.iterdir()):
        _remove_path(child)

    for skill_id, source in sorted(selected.items()):
        if not source.is_dir():
            continue
        destination = target_root / skill_id
        shutil.copytree(source, destination, ignore=_ignore_runtime_files(source), symlinks=False)
        _make_read_only(destination)

    _make_read_only(target_root)


def _ignore_runtime_files(source_root: Path) -> Callable[[str, list[str]], set[str]]:
    def ignore(directory: str, names: list[str]) -> set[str]:
        root = Path(directory)
        ignored: set[str] = set()
        for name in names:
            path = root / name
            try:
                relative = path.relative_to(source_root)
            except ValueError:
                relative = Path(name)
            if relative.as_posix() == "skill.py":
                ignored.add(name)
                continue
            if name.startswith(".") or name == "__pycache__" or path.is_symlink():
                ignored.add(name)
        return ignored

    return ignore


def _remove_legacy_workspace_mirror(path: Path) -> None:
    if not path.exists():
        return
    _make_writable(path)
    _remove_path(path)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _make_writable(root: Path) -> None:
    if not root.exists():
        return
    try:
        root.chmod(0o700)
    except OSError:
        pass
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError:
            pass


def _make_read_only(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        try:
            if path.is_dir():
                path.chmod(0o555)
            else:
                mode = stat.S_IMODE(path.stat().st_mode)
                path.chmod((mode | 0o444) & ~0o222)
        except OSError:
            pass
    try:
        root.chmod(0o555)
    except OSError:
        pass
