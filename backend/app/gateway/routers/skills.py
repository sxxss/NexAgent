"""Skills marketplace, installation, and package inspection routes."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from posixpath import dirname as posix_dirname
from posixpath import relpath as posix_relpath
from urllib.parse import urlparse

import httpx
import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

router = APIRouter()

MAX_REMOTE_BYTES = 25 * 1024 * 1024
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ZIP_FILES = 200
MAX_ZIP_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 10 * 1024 * 1024
BLOCKED_ARCHIVE_EXTENSIONS = {".bat", ".cmd", ".com", ".dll", ".exe", ".msi", ".ps1", ".scr", ".vbs"}


BUILTIN_SKILL_REGISTRY = [
    {
        "id": "knowledge-base",
        "name": "Knowledge Base",
        "description": "Prompt and tool support for RAG knowledge-base search.",
        "version": "0.1.0",
        "tags": ["knowledge", "rag"],
    },
    {
        "id": "knowledge-graph",
        "name": "Knowledge Graph",
        "description": "Prompt and tool support for graph-aware knowledge workflows.",
        "version": "0.1.0",
        "tags": ["knowledge", "graph"],
    },
    {
        "id": "deep-research",
        "name": "Deep Research",
        "description": "Prompt and tool support for delegated multi-step research.",
        "version": "0.1.0",
        "tags": ["research"],
    },
]


class SkillInstallRequest(BaseModel):
    id: str
    force: bool = False


class SkillRemoteInstallRequest(BaseModel):
    source: str
    id: str | None = None
    subdir: str = ""
    branch: str = "main"
    force: bool = False


class SkillRemoteListRequest(BaseModel):
    source: str
    branch: str = "main"


class SkillCustomRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    content: str = ""
    version: str = "0.1.0"
    tags: list[str] = Field(default_factory=list)
    required_mcp_ids: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    force: bool = False


class SkillUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    version: str | None = None
    tags: list[str] | None = None
    required_mcp_ids: list[str] | None = None
    required_tools: list[str] | None = None


class SkillFileUpdateRequest(BaseModel):
    content: str


@router.get("/registry")
async def registry():
    """Return installable skill marketplace entries."""
    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()
    installed = {skill.id: skill for skill in loader.load_all()}
    return {
        "registry": [
            {
                **item,
                "installed": item["id"] in installed,
                "content_hash": installed[item["id"]].content_hash if item["id"] in installed else "",
                "issues": [issue.to_dict() for issue in installed[item["id"]].validation_issues]
                if item["id"] in installed else [],
            }
            for item in BUILTIN_SKILL_REGISTRY
        ]
    }


@router.get("/")
async def list_skills():
    """List installed skills with package metadata."""
    from nexagent.skills.loader import SkillLoader
    from nexagent.skills.validation import dependency_issues

    loader = SkillLoader()
    skills = []
    for skill in loader.load_all():
        dep_issues = await dependency_issues(skill, loader=loader)
        issues = [
            *[issue.to_dict() for issue in skill.validation_issues],
            *[issue.to_dict() for issue in dep_issues],
        ]
        skills.append({
            **skill.to_dict(),
            "content_preview": (skill.content[:300] + "..." if len(skill.content) > 300 else skill.content),
            "issues": issues,
            "installed": True,
        })
    return {"skills": skills, "total": len(skills)}


@router.post("/install", status_code=201)
async def install(body: SkillInstallRequest):
    """Install a built-in skill.

    Built-in skills already live in ``skills/public`` in this repo, so this
    endpoint is idempotent and returns the existing installed skill.
    """
    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()
    if body.id not in {item["id"] for item in BUILTIN_SKILL_REGISTRY}:
        raise HTTPException(status_code=404, detail=f"Skill '{body.id}' is not in the built-in registry")
    skill = loader.load(body.id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{body.id}' files are missing")
    return _skill_response(skill)


@router.post("/install/remote", status_code=201)
async def install_remote(body: SkillRemoteInstallRequest):
    """Install a skill package from GitHub, a zip URL, or a raw SKILL.md URL."""
    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()
    try:
        payload, filename = await _download_remote_skill_source(body.source, body.branch, max_bytes=MAX_REMOTE_BYTES)
        with tempfile.TemporaryDirectory(prefix="nexagent-skill-remote-") as tmp:
            tmp_path = Path(tmp)
            if _looks_like_zip(filename, payload):
                candidate = _extract_skill_zip_candidate(payload, tmp_path, body.subdir, body.id)
                skill_id = _target_skill_id(candidate, body.id)
                target = _install_skill_dir(candidate, loader.public_dir, skill_id, force=body.force)
            else:
                skill_id = _slugify(body.id or Path(urlparse(body.source).path).stem or "remote-skill")
                target = _install_skill_md(payload.decode("utf-8"), loader.public_dir, skill_id, force=body.force)
    except HTTPException:
        raise
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Remote markdown is not valid UTF-8") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to install remote skill: {exc}") from exc

    loader.reload()
    skill = loader.load(target.name)
    if skill is None:
        raise HTTPException(status_code=400, detail="Installed package does not contain a valid SKILL.md")
    return _skill_response(skill)


@router.post("/remote/list")
async def list_remote_skills(body: SkillRemoteListRequest):
    """Discover installable skills from a remote repo, zip URL, or raw markdown URL without writing files."""
    try:
        payload, filename = await _download_remote_skill_source(body.source, body.branch, max_bytes=MAX_REMOTE_BYTES)
        if _looks_like_zip(filename, payload):
            candidates = _list_skill_candidates_from_zip(payload)
        else:
            skill_id = _slugify(Path(urlparse(body.source).path).stem or "remote-skill")
            candidate = _preview_markdown_skill(payload.decode("utf-8"), skill_id)
            candidates = [candidate]
    except HTTPException:
        raise
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Remote markdown is not valid UTF-8") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to list remote skills: {exc}") from exc

    return {"skills": candidates, "total": len(candidates)}


@router.post("/upload", status_code=201)
async def upload_skill(
    file: UploadFile = File(...),
    id: str | None = Form(default=None),
    force: bool = Form(default=False),
):
    """Install a skill from an uploaded .zip, .skill, or .md file."""
    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()
    payload = await file.read()
    _ensure_payload_size(payload, MAX_UPLOAD_BYTES, "Uploaded file")
    filename = file.filename or ""
    try:
        with tempfile.TemporaryDirectory(prefix="nexagent-skill-upload-") as tmp:
            tmp_path = Path(tmp)
            if _looks_like_zip(filename, payload):
                source_dir = _extract_skill_zip(payload, tmp_path)
                candidate = _select_skill_candidate(source_dir, "", id)
                skill_id = _target_skill_id(candidate, id)
                target = _install_skill_dir(candidate, loader.public_dir, skill_id, force=force)
            else:
                if not filename.lower().endswith((".md", ".markdown")):
                    raise HTTPException(status_code=400, detail="Upload a .zip, .skill, .md, or .markdown file")
                skill_id = _slugify(id or Path(filename).stem or "uploaded-skill")
                target = _install_skill_md(payload.decode("utf-8"), loader.public_dir, skill_id, force=force)
    except HTTPException:
        raise
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Uploaded markdown is not valid UTF-8") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to install uploaded skill: {exc}") from exc

    loader.reload()
    skill = loader.load(target.name)
    if skill is None:
        raise HTTPException(status_code=400, detail="Installed package does not contain a valid SKILL.md")
    return _skill_response(skill)


@router.post("/custom", status_code=201)
async def custom(body: SkillCustomRequest):
    """Install a custom documentation-only skill from request body."""
    from nexagent.skills.loader import SkillLoader

    if not body.id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Skill id may only contain letters, numbers, '-' and '_'")

    loader = SkillLoader()
    target = loader.public_dir / body.id
    if target.exists() and not body.force:
        existing = loader.load(body.id)
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Skill '{body.id}' already exists",
                "content_hash": existing.content_hash if existing else "",
                "fix": "Use update, delete the existing skill, or pass force=true to overwrite.",
            },
        )
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=False)
    skill_md = target / "SKILL.md"
    _write_skill_md(
        skill_md,
        skill_id=body.id,
        name=body.name,
        description=body.description,
        version=body.version,
        tags=body.tags,
        required_mcp_ids=body.required_mcp_ids,
        required_tools=body.required_tools,
        content=body.content or f"# {body.name}\n\n{body.description}",
    )
    loader.reload()
    skill = loader.load(body.id)
    if skill is None:
        return {"id": body.id}
    return _skill_response(skill)


@router.put("/{skill_id}")
async def update(skill_id: str, body: SkillUpdateRequest):
    """Update a local skill's SKILL.md content."""
    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()
    target = loader.public_dir / skill_id / "SKILL.md"
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    current = loader.load(skill_id)
    name = body.name or (current.name if current else skill_id)
    description = body.description if body.description is not None else (current.description if current else "")
    content = body.content if body.content is not None else (current.content if current else "")
    _write_skill_md(
        target,
        skill_id=skill_id,
        name=name,
        description=description,
        version=body.version or (current.version if current else "0.1.0"),
        tags=body.tags if body.tags is not None else (current.tags if current else []),
        required_mcp_ids=body.required_mcp_ids
        if body.required_mcp_ids is not None else (current.required_mcp_ids if current else []),
        required_tools=body.required_tools
        if body.required_tools is not None else (current.required_tools if current else []),
        content=content,
    )
    try:
        from nexagent.tools.builtin.skill_manager import _append_history, _text_hash

        _append_history(skill_id, {
            "action": "edit",
            "source": "api",
            "file_path": "SKILL.md",
            "new_hash": _text_hash(target.read_text(encoding="utf-8", errors="replace")),
        })
    except Exception:
        pass
    loader.reload()
    skill = loader.load(skill_id)
    if skill is None:
        return {"id": skill_id}
    return _skill_response(skill)


@router.post("/{skill_id}/test")
async def test(skill_id: str):
    """Check whether a skill can be loaded and its declared dependencies resolve."""
    from nexagent.skills.loader import SkillLoader
    from nexagent.skills.validation import dependency_issues

    loader = SkillLoader()
    skill = loader.load(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    dep_issues = await dependency_issues(skill, loader=loader)
    issues = [
        *[issue.to_dict() for issue in skill.validation_issues],
        *[issue.to_dict() for issue in dep_issues],
    ]
    return {
        "ok": not any(issue["severity"] == "error" for issue in issues),
        "message": "Skill loaded successfully" if not issues else "Skill loaded with issues",
        "content_hash": skill.content_hash,
        "issues": issues,
    }


@router.delete("/{skill_id}", status_code=204)
async def uninstall(skill_id: str):
    """Uninstall a skill folder from the local skills directory."""
    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()
    target = loader.public_dir / skill_id
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    shutil.rmtree(target)


@router.get("/{skill_id}/files/content")
async def skill_file_content(skill_id: str, path: str):
    """Return text content for one file inside an installed skill directory."""
    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()
    skill = loader.load(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    root = (loader.public_dir / skill_id).resolve()
    target = (root / path).resolve()
    if not _is_relative_to(target, root) or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Skill file '{path}' not found")

    rel_path = target.relative_to(root).as_posix()
    if _is_probably_binary_file(target):
        return {
            "path": rel_path,
            "text": False,
            "markdown": False,
            "content": "",
            "truncated": False,
            "size": target.stat().st_size,
        }

    max_chars = 200_000
    content = target.read_text(encoding="utf-8", errors="replace")
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]
    return {
        "path": rel_path,
        "text": True,
        "markdown": target.suffix.lower() in {".md", ".markdown"},
        "content": content,
        "truncated": truncated,
        "size": target.stat().st_size,
    }


@router.put("/{skill_id}/files/content")
async def update_skill_file_content(skill_id: str, path: str, body: SkillFileUpdateRequest):
    """Write one bundled text resource inside an installed skill directory."""
    from nexagent.skills.loader import SkillLoader
    from nexagent.tools.builtin.skill_manager import _append_history, _scan_skill_text, _text_hash

    loader = SkillLoader()
    skill = loader.load(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    rel_path = _safe_skill_resource_path(path)
    root = (loader.public_dir / skill_id).resolve()
    target = (root / rel_path).resolve()
    if not _is_relative_to(target, root):
        raise HTTPException(status_code=400, detail="Skill file path escapes the skill directory")
    if not _is_text_file_path(rel_path):
        raise HTTPException(status_code=400, detail="Only text resource files can be edited")
    scan = _scan_skill_text(body.content, executable=rel_path.startswith("scripts/"), location=f"{skill_id}/{rel_path}")
    if scan["decision"] == "block":
        raise HTTPException(status_code=400, detail=f"Security scan blocked this file: {scan['reason']}")
    previous = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")
    _append_history(skill_id, {
        "action": "write_file",
        "source": "api",
        "file_path": rel_path,
        "prev_hash": _text_hash(previous) if previous is not None else "",
        "new_hash": _text_hash(body.content),
        "scanner": scan,
    })
    loader.reload()
    return await skill_file_content(skill_id, rel_path)


@router.delete("/{skill_id}/files/content", status_code=204)
async def delete_skill_file_content(skill_id: str, path: str):
    """Delete one bundled resource file inside an installed skill directory."""
    from nexagent.skills.loader import SkillLoader
    from nexagent.tools.builtin.skill_manager import _append_history, _text_hash

    loader = SkillLoader()
    if not loader.load(skill_id):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    rel_path = _safe_skill_resource_path(path)
    if rel_path == "SKILL.md":
        raise HTTPException(status_code=400, detail="SKILL.md cannot be deleted from this endpoint")
    root = (loader.public_dir / skill_id).resolve()
    target = (root / rel_path).resolve()
    if not _is_relative_to(target, root) or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Skill file '{path}' not found")
    previous = target.read_text(encoding="utf-8", errors="replace") if _is_text_file_path(rel_path) else ""
    target.unlink()
    _append_history(skill_id, {
        "action": "remove_file",
        "source": "api",
        "file_path": rel_path,
        "prev_hash": _text_hash(previous) if previous else "",
    })
    loader.reload()


@router.get("/{skill_id}/history")
async def skill_history(skill_id: str, limit: int = 20):
    """Return recent managed Skill edit history."""
    from nexagent.tools.builtin.skill_manager import _read_history

    return {"id": skill_id, "history": _read_history(skill_id, limit=max(1, min(limit, 100)))}


def _write_skill_md(
    path,
    *,
    skill_id: str,
    name: str,
    description: str,
    version: str,
    tags: list[str],
    required_mcp_ids: list[str],
    required_tools: list[str],
    content: str,
) -> None:
    metadata = {
        "id": skill_id,
        "name": name,
        "description": description,
        "version": version,
        "tags": tags,
        "required_mcp_ids": required_mcp_ids,
        "required_tools": required_tools,
    }
    import yaml

    path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + content,
        encoding="utf-8",
    )


async def _download_remote_skill_source(source: str, branch: str, *, max_bytes: int) -> tuple[bytes, str]:
    url = _remote_source_to_url(source.strip(), branch.strip() or "main")
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        response = await client.get(url)
        if response.status_code == 404 and branch != "master" and "github.com" in url:
            fallback = _remote_source_to_url(source.strip(), "master")
            response = await client.get(fallback)
            url = fallback
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            raise HTTPException(status_code=413, detail=f"Remote skill package is too large: {content_length} bytes")
        _ensure_payload_size(response.content, max_bytes, "Remote skill package")
        filename = Path(urlparse(url).path).name or "remote-skill"
        return response.content, filename


def _remote_source_to_url(source: str, branch: str) -> str:
    if not source:
        raise HTTPException(status_code=400, detail="Remote source is required")
    if source.startswith(("http://", "https://")):
        parsed = urlparse(source)
        if parsed.netloc.lower() == "github.com":
            parts = [part for part in parsed.path.strip("/").split("/") if part]
            if len(parts) >= 2 and "archive" not in parts and not source.lower().endswith((".zip", ".md")):
                return f"https://github.com/{parts[0]}/{parts[1]}/archive/refs/heads/{branch}.zip"
        return source
    if "/" in source and len(source.split("/")) == 2:
        owner, repo = source.split("/", 1)
        return f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    raise HTTPException(status_code=400, detail="Use owner/repo, a GitHub URL, a zip URL, or a raw SKILL.md URL")


def _looks_like_zip(filename: str, payload: bytes) -> bool:
    return filename.lower().endswith((".zip", ".skill")) or payload.startswith(b"PK\x03\x04")


def _extract_skill_zip(payload: bytes, tmp_path: Path) -> Path:
    archive = tmp_path / "skill.zip"
    archive.write_bytes(payload)
    extract_root = tmp_path / "extract"
    extract_root.mkdir()
    with zipfile.ZipFile(archive) as zf:
        members = [member for member in zf.infolist() if not member.is_dir()]
        if len(members) > MAX_ZIP_FILES:
            raise HTTPException(status_code=413, detail=f"Skill archive contains too many files: {len(members)}")
        total_size = sum(member.file_size for member in members)
        if total_size > MAX_ZIP_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Skill archive is too large after extraction: {total_size} bytes",
            )
        for member in zf.infolist():
            member_path = Path(member.filename)
            if member.is_dir():
                continue
            if member_path.is_absolute() or ".." in member_path.parts:
                raise HTTPException(status_code=400, detail=f"Unsafe path in archive: {member.filename}")
            if member.file_size > MAX_ZIP_MEMBER_BYTES:
                raise HTTPException(status_code=413, detail=f"Archive member is too large: {member.filename}")
            if member_path.suffix.lower() in BLOCKED_ARCHIVE_EXTENSIONS:
                raise HTTPException(status_code=400, detail=f"Blocked file type in archive: {member.filename}")
            target = extract_root / member_path
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return extract_root


def _list_skill_candidates_from_zip(payload: bytes) -> list[dict]:
    candidates = []
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        members = [member for member in zf.infolist() if not member.is_dir()]
        skill_dirs = sorted(
            {posix_dirname(member.filename) for member in members if member.filename.endswith("SKILL.md")}
        )
        for skill_dir in skill_dirs:
            skill_md_name = f"{skill_dir}/SKILL.md" if skill_dir else "SKILL.md"
            try:
                skill_md = zf.read(skill_md_name).decode("utf-8")
            except KeyError:
                continue
            metadata = _read_frontmatter_from_text(skill_md)
            body = _body_from_text(skill_md)
            skill_id = _slugify(str(metadata.get("id") or metadata.get("name") or Path(skill_dir).name))
            files = _preview_zip_skill_files(zf, skill_dir)
            candidates.append({
                "id": skill_id,
                "name": str(metadata.get("name") or skill_id),
                "description": str(metadata.get("description") or _first_content_line(body) or ""),
                "version": str(metadata.get("version") or "0.1.0"),
                "tags": _metadata_string_list(metadata.get("tags", [])),
                "required_mcp_ids": _metadata_string_list(metadata.get("required_mcp_ids", [])),
                "required_tools": _metadata_string_list(metadata.get("required_tools", [])),
                "subdir": skill_dir,
                "file_count": len(files),
                "files": files,
                "content_hash": _zip_skill_hash(zf, skill_dir),
                "content_preview": body[:300] + ("..." if len(body) > 300 else ""),
            })
    return candidates


def _extract_skill_zip_candidate(
    payload: bytes,
    tmp_path: Path,
    subdir: str,
    requested_id: str | None,
) -> Path:
    candidates = _list_skill_candidates_from_zip(payload)
    if not candidates:
        raise HTTPException(status_code=400, detail="Archive does not contain SKILL.md")

    selected = _select_zip_candidate(candidates, subdir, requested_id)
    selected_subdir = selected["subdir"].strip("/")
    extract_root = tmp_path / "extract"
    target_root = extract_root / (Path(selected_subdir).name if selected_subdir else selected["id"])
    target_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(BytesIO(payload)) as zf:
        selected_members = _zip_members_for_skill(zf, selected_subdir)
        _validate_zip_members(selected_members)
        for member in selected_members:
            relative = posix_relpath(member.filename, selected_subdir) if selected_subdir else member.filename
            target = target_root / Path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return target_root


def _select_zip_candidate(candidates: list[dict], subdir: str, requested_id: str | None) -> dict:
    if subdir:
        normalized = subdir.strip("/")
        for candidate in candidates:
            if candidate["subdir"].strip("/") == normalized:
                return candidate
        raise HTTPException(status_code=400, detail=f"Skill subdir '{subdir}' was not found in archive")

    if requested_id:
        slug = _slugify(requested_id)
        for candidate in candidates:
            if candidate["id"] == slug or Path(candidate["subdir"]).name == slug:
                return candidate

    if len(candidates) > 1:
        names = ", ".join(candidate["subdir"] for candidate in candidates[:8])
        raise HTTPException(
            status_code=400,
            detail=f"Archive contains multiple skills. Provide id or subdir. Candidates: {names}",
        )
    return candidates[0]


def _zip_members_for_skill(zf: zipfile.ZipFile, skill_dir: str) -> list[zipfile.ZipInfo]:
    prefix = f"{skill_dir.strip('/')}/" if skill_dir.strip("/") else ""
    result = []
    for member in zf.infolist():
        if member.is_dir():
            continue
        if prefix and not member.filename.startswith(prefix):
            continue
        result.append(member)
    return result


def _validate_zip_members(members: list[zipfile.ZipInfo]) -> None:
    if len(members) > MAX_ZIP_FILES:
        raise HTTPException(status_code=413, detail=f"Skill archive contains too many files: {len(members)}")
    total_size = sum(member.file_size for member in members)
    if total_size > MAX_ZIP_TOTAL_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Skill archive is too large after extraction: {total_size} bytes",
        )
    for member in members:
        member_path = Path(member.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise HTTPException(status_code=400, detail=f"Unsafe path in archive: {member.filename}")
        if member.file_size > MAX_ZIP_MEMBER_BYTES:
            raise HTTPException(status_code=413, detail=f"Archive member is too large: {member.filename}")
        if member_path.suffix.lower() in BLOCKED_ARCHIVE_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Blocked file type in archive: {member.filename}")


def _preview_zip_skill_files(zf: zipfile.ZipFile, skill_dir: str) -> list[dict]:
    files = []
    for member in _zip_members_for_skill(zf, skill_dir):
        rel = posix_relpath(member.filename, skill_dir) if skill_dir else member.filename
        files.append({
            "path": rel,
            "size": member.file_size,
            "kind": _skill_file_kind(rel),
            "text": _is_text_file_path(rel),
        })
    return sorted(files, key=lambda item: item["path"])[:80]


def _zip_skill_hash(zf: zipfile.ZipFile, skill_dir: str) -> str:
    import hashlib

    sha = hashlib.sha256()
    for member in sorted(_zip_members_for_skill(zf, skill_dir), key=lambda item: item.filename):
        rel = posix_relpath(member.filename, skill_dir) if skill_dir else member.filename
        sha.update(rel.encode("utf-8"))
        sha.update(b"\0")
        sha.update(zf.read(member))
    return sha.hexdigest()


def _select_skill_candidate(root: Path, subdir: str, requested_id: str | None) -> Path:
    if subdir:
        candidate = (root / subdir).resolve()
        if not _is_relative_to(candidate, root.resolve()) or not (candidate / "SKILL.md").exists():
            raise HTTPException(status_code=400, detail=f"Skill subdir '{subdir}' was not found in archive")
        return candidate

    candidates = sorted(path.parent for path in root.rglob("SKILL.md"))
    if not candidates:
        raise HTTPException(status_code=400, detail="Archive does not contain SKILL.md")
    if requested_id:
        slug = _slugify(requested_id)
        for candidate in candidates:
            if candidate.name == slug:
                return candidate
            metadata = _read_skill_frontmatter(candidate / "SKILL.md")
            metadata_id = str(metadata.get("id") or metadata.get("name") or "")
            if metadata_id and _slugify(metadata_id) == slug:
                return candidate
    if len(candidates) > 1:
        names = ", ".join(path.relative_to(root).as_posix() for path in candidates[:8])
        raise HTTPException(
            status_code=400,
            detail=f"Archive contains multiple skills. Provide id or subdir. Candidates: {names}",
        )
    return candidates[0]


def _list_skill_candidates(root: Path) -> list[dict]:
    candidates = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        metadata = _read_skill_frontmatter(skill_md)
        body = _read_skill_body(skill_md)
        skill_id = _slugify(str(metadata.get("id") or metadata.get("name") or skill_dir.name))
        files = _preview_files(skill_dir)
        candidates.append({
            "id": skill_id,
            "name": str(metadata.get("name") or skill_id),
            "description": str(metadata.get("description") or _first_content_line(body) or ""),
            "version": str(metadata.get("version") or "0.1.0"),
            "tags": _metadata_string_list(metadata.get("tags", [])),
            "required_mcp_ids": _metadata_string_list(metadata.get("required_mcp_ids", [])),
            "required_tools": _metadata_string_list(metadata.get("required_tools", [])),
            "subdir": skill_dir.relative_to(root).as_posix(),
            "file_count": len(files),
            "files": files,
            "content_hash": _directory_hash(skill_dir),
            "content_preview": body[:300] + ("..." if len(body) > 300 else ""),
        })
    return candidates


def _preview_markdown_skill(content: str, skill_id: str) -> dict:
    metadata = _read_frontmatter_from_text(content)
    body = _body_from_text(content)
    return {
        "id": _slugify(str(metadata.get("id") or metadata.get("name") or skill_id)),
        "name": str(metadata.get("name") or skill_id),
        "description": str(metadata.get("description") or _first_content_line(body) or ""),
        "version": str(metadata.get("version") or "0.1.0"),
        "tags": _metadata_string_list(metadata.get("tags", [])),
        "required_mcp_ids": _metadata_string_list(metadata.get("required_mcp_ids", [])),
        "required_tools": _metadata_string_list(metadata.get("required_tools", [])),
        "subdir": "",
        "file_count": 1,
        "files": [{"path": "SKILL.md", "size": len(content.encode("utf-8")), "kind": "entry", "text": True}],
        "content_hash": _bytes_hash(content.encode("utf-8")),
        "content_preview": body[:300] + ("..." if len(body) > 300 else ""),
    }


def _install_skill_dir(source: Path, public_dir: Path, skill_id: str, *, force: bool) -> Path:
    target = public_dir / _slugify(skill_id)
    _ensure_install_target(target, force=force)
    public_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    _normalize_installed_skill_md(target / "SKILL.md", target.name)
    return target


def _install_skill_md(content: str, public_dir: Path, skill_id: str, *, force: bool) -> Path:
    target = public_dir / _slugify(skill_id)
    _ensure_install_target(target, force=force)
    target.mkdir(parents=True, exist_ok=False)
    skill_md = target / "SKILL.md"
    if content.lstrip().startswith("---"):
        skill_md.write_text(content, encoding="utf-8")
        _normalize_installed_skill_md(skill_md, target.name)
    else:
        _write_skill_md(
            skill_md,
            skill_id=target.name,
            name=target.name,
            description="Uploaded markdown skill",
            version="0.1.0",
            tags=[],
            required_mcp_ids=[],
            required_tools=[],
            content=content,
        )
    return target


def _ensure_install_target(target: Path, *, force: bool) -> None:
    if target.exists() and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Skill '{target.name}' already exists",
                "fix": "Enable overwrite or choose a different id.",
            },
        )
    if target.exists():
        shutil.rmtree(target)


def _normalize_installed_skill_md(path: Path, skill_id: str) -> None:
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        metadata = yaml.safe_load(parts[1]) or {} if len(parts) >= 3 else {}
        body = parts[2].strip() if len(parts) >= 3 else raw
    else:
        metadata = {}
        body = raw
    metadata.setdefault("id", skill_id)
    metadata.setdefault("name", skill_id)
    metadata.setdefault("description", _first_content_line(body) or f"{skill_id} skill")
    metadata.setdefault("version", "0.1.0")
    path.write_text(
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + body.strip()
        + "\n",
        encoding="utf-8",
    )


def _target_skill_id(candidate: Path, requested_id: str | None) -> str:
    metadata = _read_skill_frontmatter(candidate / "SKILL.md")
    return _slugify(requested_id or str(metadata.get("id") or metadata.get("name") or candidate.name))


def _read_skill_frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    return _read_frontmatter_from_text(raw)


def _read_frontmatter_from_text(raw: str) -> dict:
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    data = yaml.safe_load(parts[1]) or {}
    return data if isinstance(data, dict) else {}


def _read_skill_body(path: Path) -> str:
    return _body_from_text(path.read_text(encoding="utf-8"))


def _body_from_text(raw: str) -> str:
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return raw.strip()


def _metadata_string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _preview_files(root: Path) -> list[dict]:
    files = []
    paths = sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for path in paths:
        rel = path.relative_to(root).as_posix()
        files.append({
            "path": rel,
            "size": path.stat().st_size,
            "kind": _skill_file_kind(rel),
            "text": _is_text_file_path(rel),
        })
    return files[:80]


def _is_text_file_path(path: str) -> bool:
    return Path(path).suffix.lower() not in {
        ".7z",
        ".avif",
        ".bin",
        ".bmp",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".tar",
        ".webp",
        ".zip",
    }


def _skill_file_kind(path: str) -> str:
    if path == "SKILL.md":
        return "entry"
    if path.startswith("scripts/"):
        return "script"
    return "resource"


def _is_probably_binary_file(path: Path) -> bool:
    if not _is_text_file_path(path.name):
        return True
    try:
        return b"\0" in path.read_bytes()[:4096]
    except OSError:
        return True


def _directory_hash(root: Path) -> str:
    import hashlib

    sha = hashlib.sha256()
    paths = sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for path in paths:
        rel = path.relative_to(root).as_posix()
        sha.update(rel.encode("utf-8"))
        sha.update(b"\0")
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                sha.update(chunk)
    return sha.hexdigest()


def _bytes_hash(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _ensure_payload_size(payload: bytes, max_bytes: int, label: str) -> None:
    if len(payload) > max_bytes:
        raise HTTPException(status_code=413, detail=f"{label} is too large: {len(payload)} bytes")


def _first_content_line(content: str) -> str:
    for line in content.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:160]
    return ""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-_").lower()
    if not slug:
        raise HTTPException(status_code=400, detail="Skill id is required")
    if len(slug) > 64:
        slug = slug[:64].strip("-_")
    return slug if slug else "skill"


def _safe_skill_resource_path(value: str) -> str:
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise HTTPException(status_code=400, detail=f"Invalid skill file path: {value}")
    if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
        raise HTTPException(status_code=400, detail=f"Hidden or cache paths are not allowed: {value}")
    return path.as_posix()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _skill_response(skill) -> dict:
    return {
        **skill.to_dict(),
        "content_preview": (skill.content[:300] + "..." if len(skill.content) > 300 else skill.content),
        "issues": [issue.to_dict() for issue in skill.validation_issues],
        "installed": True,
    }
