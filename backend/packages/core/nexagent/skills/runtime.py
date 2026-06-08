"""Runtime preparation for standard progressive Skills."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

from nexagent.skills.loader import Skill


def prepare_skill_runtime(thread_id: str, skills: list[Skill]) -> None:
    """Expose selected Skills in the per-thread sandbox namespace.

    Two mirrors are prepared:
    - ``/mnt/skills/<id>`` via ``VirtualPathTranslator.SKILLS`` for file tools.
    - ``skills/<id>`` under the workspace so bash can execute bundled scripts.
    """
    from nexagent.config import get_config
    from nexagent.sandbox.sandbox import VirtualPathTranslator

    translator = VirtualPathTranslator(get_config().sandbox.base_dir)
    thread_root = translator.thread_root(thread_id)
    selected = {skill.id: skill.path.parent.resolve() for skill in skills}
    _sync_root(thread_root / "skills", selected)
    _sync_root(thread_root / "workspace" / "skills", selected)


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
        shutil.copytree(source, destination, ignore=_ignore_runtime_files, symlinks=False)
        _make_read_only(destination)

    _make_read_only(target_root)


def _ignore_runtime_files(directory: str, names: list[str]) -> set[str]:
    root = Path(directory)
    ignored: set[str] = set()
    for name in names:
        path = root / name
        if name.startswith(".") or name == "__pycache__" or path.is_symlink():
            ignored.add(name)
    return ignored


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
