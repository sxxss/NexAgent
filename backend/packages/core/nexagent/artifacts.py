"""Thread artifact discovery and safe file access."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

from nexagent.sandbox.sandbox import VirtualPathTranslator

TEXT_PREVIEW_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".htm",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".css",
    ".xml",
    ".log",
}


@dataclass(frozen=True)
class ArtifactMeta:
    thread_id: str
    path: str
    name: str
    size: int
    mime_type: str
    previewable: bool
    download_url: str
    preview_url: str

    def to_dict(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "path": self.path,
            "name": self.name,
            "size": self.size,
            "mime_type": self.mime_type,
            "previewable": self.previewable,
            "download_url": self.download_url,
            "preview_url": self.preview_url,
        }


def get_translator() -> VirtualPathTranslator:
    from nexagent.config import get_config

    return VirtualPathTranslator(get_config().sandbox.base_dir)


def list_thread_artifacts(thread_id: str) -> list[ArtifactMeta]:
    translator = get_translator()
    outputs = translator.to_real(VirtualPathTranslator.OUTPUTS, thread_id)
    if not outputs.exists():
        return []
    artifacts: list[ArtifactMeta] = []
    for path in sorted(outputs.rglob("*"), key=lambda item: item.as_posix().lower()):
        if path.is_file():
            artifacts.append(_meta_for_path(translator, thread_id, path))
    return artifacts


def resolve_artifact(thread_id: str, virtual_path: str) -> Path:
    translator = get_translator()
    path = translator.to_real(virtual_path, thread_id)
    outputs = translator.to_real(VirtualPathTranslator.OUTPUTS, thread_id)
    resolved = path.resolve()
    outputs_resolved = outputs.resolve()
    if resolved != outputs_resolved and outputs_resolved not in resolved.parents:
        raise ValueError("Artifact path must be under /mnt/user-data/outputs.")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(virtual_path)
    return resolved


def read_artifact_preview(thread_id: str, virtual_path: str, max_chars: int = 20000) -> dict:
    path = resolve_artifact(thread_id, virtual_path)
    meta = _meta_for_path(get_translator(), thread_id, path)
    if not meta.previewable:
        return {**meta.to_dict(), "content": "", "truncated": False}
    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > max_chars
    return {
        **meta.to_dict(),
        "content": text[:max_chars],
        "truncated": truncated,
    }


def _meta_for_path(translator: VirtualPathTranslator, thread_id: str, path: Path) -> ArtifactMeta:
    virtual = translator.to_virtual(path, thread_id)
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    suffix = path.suffix.lower()
    previewable = mime_type.startswith("text/") or suffix in TEXT_PREVIEW_EXTENSIONS
    return ArtifactMeta(
        thread_id=thread_id,
        path=virtual,
        name=path.name,
        size=path.stat().st_size,
        mime_type=mime_type,
        previewable=previewable,
        download_url=f"/api/artifacts/threads/{thread_id}/download?path={_quote(virtual)}",
        preview_url=f"/api/artifacts/threads/{thread_id}/preview?path={_quote(virtual)}",
    )


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
