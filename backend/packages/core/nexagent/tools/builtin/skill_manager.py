"""Built-in tools for creating managed NexAgent skills."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

MAX_RESOURCE_FILES = 60
MAX_RESOURCE_CHARS = 120_000
MAX_READ_SKILL_CHARS = 24_000
DEFAULT_READ_SKILL_CHARS = 12_000
HISTORY_DIR_NAME = ".history"
SUPPORT_FILE_DIRS = {"references", "scripts", "test-cases", "evals", "examples", "templates", "assets"}
_SKILL_LOCKS: dict[str, Any] = {}


class SkillResourceFile(BaseModel):
    path: str = Field(
        ...,
        description=(
            "Relative path inside the skill folder, for example references/template.md, "
            "scripts/parser.py, test-cases/basic.md, evals/evals.json, or assets/schema.json."
        ),
    )
    content: str = Field(..., description="UTF-8 text content for the resource file.")


class ReadSkillInput(BaseModel):
    id: str = Field(..., description="Managed skill id to inspect.")
    path: str = Field(
        default="",
        description=(
            "Optional relative file path to read. Empty returns SKILL.md only. "
            "Use this for referenced resources such as scripts/, references/, templates/, or examples/."
        ),
    )
    max_chars: int = Field(default=DEFAULT_READ_SKILL_CHARS, ge=1, le=MAX_READ_SKILL_CHARS)


class ListSkillsInput(BaseModel):
    query: str = Field(default="", description="Optional keyword to filter by id, name, description, or tags.")
    include_files: bool = Field(
        default=False,
        description=(
            "Include agent-safe file metadata for each matching skill. The manifest excludes local absolute paths "
            "and includes bundled resources such as scripts/ and references/."
        ),
    )


class SkillManageInput(BaseModel):
    action: Literal["create", "edit", "patch", "delete", "write_file", "remove_file", "history"] = Field(
        ...,
        description=(
            "Skill management action. Use create/edit for whole SKILL.md updates, patch for small edits, "
            "write_file/remove_file for bundled resources, and history to inspect recent changes. "
            "Agents should prefer small patch/write_file calls; avoid one huge edit payload unless replacing "
            "the whole skill."
        ),
    )
    id: str = Field(..., description="Managed skill id.")
    name: str = Field(default="", description="Human-readable name for create/edit.")
    description: str = Field(default="", description="Trigger-focused description for create/edit.")
    content: str = Field(
        default="",
        description=(
            "SKILL.md body for create/edit, or file content for write_file. Keep this concise; for improvements, "
            "prefer patch or one small support file per call."
        ),
    )
    path: str = Field(default="", description="Supporting file path for write_file/remove_file.")
    find: str = Field(default="", description="Existing text to replace for patch.")
    replace: str = Field(default="", description="Replacement text for patch.")
    expected_count: int | None = Field(default=None, ge=1, description="Optional exact match count for patch.")
    tags: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    required_mcp_ids: list[str] = Field(default_factory=list)
    files: list[SkillResourceFile] = Field(default_factory=list)
    force: bool = Field(
        default=False,
        description="Allow create to replace an existing skill or edit to create if missing.",
    )
    preserve_existing_files: bool = Field(
        default=True,
        description="When replacing, keep existing resources not supplied by this request.",
    )


def get_list_skills_tool() -> BaseTool:
    """Return a tool that lists managed Skills without filesystem probing."""

    @tool("list_skills", args_schema=ListSkillsInput)
    async def list_skills(query: str = "", include_files: bool = False) -> str:
        """List installed NexAgent Skills, optionally filtered by a keyword."""
        from nexagent.skills.loader import SkillLoader

        loader = SkillLoader()
        keyword = query.strip().lower()
        skills = []
        for skill in loader.load_all():
            searchable = " ".join([
                skill.id,
                skill.name,
                skill.description,
                " ".join(skill.tags),
            ]).lower()
            if keyword and keyword not in searchable:
                continue
            item: dict[str, Any] = {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "tags": skill.tags,
                "required_tools": skill.required_tools,
                "required_mcp_ids": skill.required_mcp_ids,
                "content_hash": skill.content_hash,
            }
            if include_files:
                item["files"] = _agent_safe_file_manifest(skill.files)
            skills.append(item)

        return _json_dumps({"skills": skills, "count": len(skills)})

    return list_skills


def get_read_skill_tool() -> BaseTool:
    """Return a tool for reading managed Skill files without filesystem MCP access."""

    @tool("read_skill", args_schema=ReadSkillInput)
    async def read_skill(id: str, path: str = "", max_chars: int = DEFAULT_READ_SKILL_CHARS) -> str:
        """Inspect an installed NexAgent Skill and return its tree plus text file contents."""
        from nexagent.skills.loader import SkillLoader

        skill_id = id.strip()
        loader = SkillLoader()
        skill = loader.load(skill_id)
        if skill is None:
            return f"Error: Skill '{skill_id}' was not found."

        root = skill.path.parent.resolve()
        requested = path.strip().replace("\\", "/")
        files = skill.files or []
        readable_paths = [
            str(file.get("path") or "")
            for file in files
            if file.get("text")
        ]
        if requested:
            try:
                relative = _safe_existing_skill_path(requested)
            except ValueError as exc:
                return f"Error: {exc}"
            if relative not in readable_paths:
                return f"Error: File '{relative}' is not a readable text file in Skill '{skill_id}'."
            paths = [relative]
        else:
            paths = ["SKILL.md"] if "SKILL.md" in readable_paths else []

        contents: list[dict[str, Any]] = []
        remaining = min(max_chars, MAX_READ_SKILL_CHARS)
        for relative in paths:
            if remaining <= 0:
                break
            file_path = (root / relative).resolve()
            if not file_path.is_file() or not file_path.is_relative_to(root):
                continue
            text = file_path.read_text(encoding="utf-8", errors="replace")
            truncated = len(text) > remaining
            content = text[:remaining]
            contents.append({"path": relative, "content": content, "truncated": truncated})
            remaining -= len(content)

        return _json_dumps({
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "storage": "managed",
            "files": _agent_safe_file_manifest(files),
            "content_hash": skill.content_hash,
            "contents": contents,
            "note": (
                "Default read returns SKILL.md only. Call read_skill with path to inspect supporting resource files. "
                "At runtime, selected Skills are mirrored read-only to /mnt/skills/<id> for file tools and "
                "skills/<id>/ for bash script execution."
            ),
        })

    return read_skill


def get_skill_manage_tool() -> BaseTool:
    """Return a DeerFlow-style tool for evolving managed Skills safely."""

    @tool("skill_manage", args_schema=SkillManageInput)
    async def skill_manage(
        action: str,
        id: str,
        name: str = "",
        description: str = "",
        content: str = "",
        path: str = "",
        find: str = "",
        replace: str = "",
        expected_count: int | None = None,
        tags: list[str] | None = None,
        required_tools: list[str] | None = None,
        required_mcp_ids: list[str] | None = None,
        files: list[SkillResourceFile] | None = None,
        force: bool = False,
        preserve_existing_files: bool = True,
    ) -> str:
        """Create, edit, patch, delete, read history, or update bundled files for a managed NexAgent Skill.

        Prefer this tool over generic filesystem tools for all Skill lifecycle work.
        It validates paths, serializes writes per Skill, records history, and reloads
        the Skill loader after successful changes.
        """
        return await _manage_skill_impl(
            action=action,
            id=id,
            name=name,
            description=description,
            content=content,
            path=path,
            find=find,
            replace=replace,
            expected_count=expected_count,
            tags=tags or [],
            required_tools=required_tools or [],
            required_mcp_ids=required_mcp_ids or [],
            files=files or [],
            force=force,
            preserve_existing_files=preserve_existing_files,
            source="skill_manage",
        )

    return skill_manage


async def _manage_skill_impl(
    *,
    action: str,
    id: str,
    name: str = "",
    description: str = "",
    content: str = "",
    path: str = "",
    find: str = "",
    replace: str = "",
    expected_count: int | None = None,
    tags: list[str] | None = None,
    required_tools: list[str] | None = None,
    required_mcp_ids: list[str] | None = None,
    files: list[SkillResourceFile] | None = None,
    force: bool = False,
    preserve_existing_files: bool = True,
    source: str = "skill_manage",
) -> str:
    from nexagent.skills.loader import SKILL_ID_PATTERN, SkillLoader

    skill_id = id.strip()
    if not SKILL_ID_PATTERN.match(skill_id):
        return "Error: Skill id must contain only letters, numbers, '-' or '_' and be 2-64 chars."

    lock = _get_skill_lock(skill_id)
    async with lock:
        loader = SkillLoader()
        target = loader.public_dir / skill_id
        normalized_action = action.strip().lower()

        if normalized_action == "history":
            records = _read_history(skill_id, limit=20)
            return _json_dumps({"ok": True, "id": skill_id, "action": "history", "history": records})

        if normalized_action in {"create", "edit"}:
            if normalized_action == "create" and target.exists() and not force:
                return (
                    f"Error: Skill '{skill_id}' already exists. Use action=edit, action=patch, "
                    "or pass force=true only when replacing is intended."
                )
            if normalized_action == "edit" and not target.exists() and not force:
                return f"Error: Skill '{skill_id}' does not exist. Use action=create or pass force=true to create it."
            result = _write_skill_package(
                loader=loader,
                skill_id=skill_id,
                name=name.strip() or skill_id,
                description=description.strip(),
                content=content,
                tags=tags or [],
                required_tools=required_tools or [],
                required_mcp_ids=required_mcp_ids or [],
                files=files or [],
                force=True,
                preserve_existing_files=preserve_existing_files,
            )
            if result.startswith("Error:"):
                return result
            _append_history(skill_id, {
                "action": normalized_action,
                "source": source,
                "file_path": "SKILL.md",
                "message": f"{normalized_action} skill package",
            })
            return result

        if normalized_action == "patch":
            skill = loader.load(skill_id)
            if skill is None or not target.exists():
                return f"Error: Skill '{skill_id}' was not found."
            if not find:
                return "Error: find is required for patch."
            raw = (target / "SKILL.md").read_text(encoding="utf-8", errors="replace")
            occurrences = raw.count(find)
            if occurrences == 0:
                return "Error: Patch target was not found in SKILL.md."
            if expected_count is not None and occurrences != expected_count:
                return f"Error: Expected {expected_count} replacements but found {occurrences}."
            replacement_count = expected_count or 1
            new_raw = raw.replace(find, replace, replacement_count)
            scan = _scan_skill_text(new_raw, executable=False, location=f"{skill_id}/SKILL.md")
            if scan["decision"] == "block":
                return f"Error: Security scan blocked patch: {scan['reason']}"
            _atomic_write(target / "SKILL.md", new_raw)
            loader.reload()
            _append_history(skill_id, {
                "action": "patch",
                "source": source,
                "file_path": "SKILL.md",
                "replacements": replacement_count,
                "matches": occurrences,
                "scanner": scan,
            })
            return _json_dumps({
                "ok": True,
                "id": skill_id,
                "action": "patch",
                "replacements": replacement_count,
                "matches": occurrences,
                "message": f"Patched Skill '{skill_id}'.",
            })

        if normalized_action == "write_file":
            if not target.exists():
                return f"Error: Skill '{skill_id}' was not found."
            if not path:
                return "Error: path is required for write_file."
            try:
                relative = _safe_resource_path(path)
            except ValueError as exc:
                return f"Error: {exc}"
            scan = _scan_skill_text(
                content,
                executable=relative.startswith("scripts/"),
                location=f"{skill_id}/{relative}",
            )
            if scan["decision"] == "block":
                return f"Error: Security scan blocked write_file: {scan['reason']}"
            file_path = target / relative
            previous = file_path.read_text(encoding="utf-8", errors="replace") if file_path.is_file() else None
            _atomic_write(file_path, content)
            loader.reload()
            _append_history(skill_id, {
                "action": "write_file",
                "source": source,
                "file_path": relative,
                "prev_hash": _text_hash(previous) if previous is not None else "",
                "new_hash": _text_hash(content),
                "scanner": scan,
            })
            return _json_dumps({"ok": True, "id": skill_id, "action": "write_file", "path": relative})

        if normalized_action == "remove_file":
            if not target.exists():
                return f"Error: Skill '{skill_id}' was not found."
            if not path:
                return "Error: path is required for remove_file."
            try:
                relative = _safe_existing_skill_path(path)
            except ValueError as exc:
                return f"Error: {exc}"
            if relative == "SKILL.md":
                return "Error: remove_file may only remove bundled resource files."
            file_path = (target / relative).resolve()
            root = target.resolve()
            if not file_path.is_file() or not file_path.is_relative_to(root):
                return f"Error: File '{relative}' was not found in Skill '{skill_id}'."
            previous = file_path.read_text(encoding="utf-8", errors="replace") if _looks_text_path(relative) else ""
            file_path.unlink()
            loader.reload()
            _append_history(skill_id, {
                "action": "remove_file",
                "source": source,
                "file_path": relative,
                "prev_hash": _text_hash(previous) if previous else "",
            })
            return _json_dumps({"ok": True, "id": skill_id, "action": "remove_file", "path": relative})

        if normalized_action == "delete":
            if not target.exists():
                return f"Error: Skill '{skill_id}' was not found."
            snapshot_hash = _directory_hash(target)
            shutil.rmtree(target)
            loader.reload()
            _append_history(skill_id, {
                "action": "delete",
                "source": source,
                "file_path": "",
                "prev_hash": snapshot_hash,
            })
            return _json_dumps({
                "ok": True,
                "id": skill_id,
                "action": "delete",
                "message": f"Deleted Skill '{skill_id}'.",
            })

        return f"Error: Unsupported skill_manage action '{action}'."


def _format_skill_md(
    *,
    skill_id: str,
    name: str,
    description: str,
    tags: list[str],
    required_tools: list[str],
    required_mcp_ids: list[str],
    content: str,
) -> str:
    frontmatter: dict[str, Any] = {
        "id": skill_id,
        "name": name,
        "description": description,
        "version": "0.1.0",
    }
    if tags:
        frontmatter["tags"] = tags
    if required_tools:
        frontmatter["required_tools"] = required_tools
    if required_mcp_ids:
        frontmatter["required_mcp_ids"] = required_mcp_ids
    body = content.strip() or f"# {name}\n\n{description}".strip()
    return "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n" + body + "\n"


def _write_skill_package(
    *,
    loader,
    skill_id: str,
    name: str,
    description: str,
    content: str,
    tags: list[str],
    required_tools: list[str],
    required_mcp_ids: list[str],
    files: list[SkillResourceFile],
    force: bool,
    preserve_existing_files: bool,
) -> str:
    validation_error = _validate_resource_files(files)
    if validation_error:
        return f"Error: {validation_error}"
    scan = _scan_skill_text(content, executable=False, location=f"{skill_id}/SKILL.md")
    if scan["decision"] == "block":
        return f"Error: Security scan blocked SKILL.md: {scan['reason']}"
    for item in files:
        relative = _safe_resource_path(item.path)
        file_scan = _scan_skill_text(
            item.content,
            executable=relative.startswith("scripts/"),
            location=f"{skill_id}/{relative}",
        )
        if file_scan["decision"] == "block":
            return f"Error: Security scan blocked {relative}: {file_scan['reason']}"

    target = loader.public_dir / skill_id
    preserved_files: dict[str, str] = {}
    if target.exists() and force and preserve_existing_files:
        preserved_files = _read_existing_resource_files(target)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=False)

    skill_md = target / "SKILL.md"
    _atomic_write(
        skill_md,
        _format_skill_md(
            skill_id=skill_id,
            name=name,
            description=description,
            tags=tags,
            required_tools=required_tools,
            required_mcp_ids=required_mcp_ids,
            content=content,
        ),
    )
    provided_paths = {_safe_resource_path(item.path) for item in files}
    for relative, existing_content in preserved_files.items():
        if relative in provided_paths:
            continue
        _atomic_write(target / relative, existing_content)
    for item in files:
        relative = _safe_resource_path(item.path)
        _atomic_write(target / relative, item.content)

    loader.reload()
    skill = loader.load(skill_id)
    if skill is None:
        return f"Error: Skill '{skill_id}' was written but could not be loaded."
    issues = [issue.to_dict() for issue in skill.validation_issues]
    if scan["decision"] == "warn":
        issues.append({
            "severity": "warning",
            "code": "skill_security_warning",
            "message": scan["reason"],
            "fix": "Review generated content before using this skill in trusted workflows.",
        })
    return _json_dumps({
        "ok": not any(issue["severity"] == "error" for issue in issues),
        "id": skill.id,
        "name": skill.name,
        "storage": "managed",
        "files": _agent_safe_file_manifest(skill.files),
        "issues": issues,
        "message": f"Skill '{skill.id}' saved in managed skill storage.",
    })


def _agent_safe_file_manifest(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for file in files:
        path = str(file.get("path") or "")
        result.append({
            "path": path,
            "size": file.get("size"),
            "kind": file.get("kind"),
            "text": file.get("text"),
        })
    return result


def _validate_resource_files(files: list[SkillResourceFile]) -> str:
    if len(files) > MAX_RESOURCE_FILES:
        return f"Too many resource files: {len(files)} > {MAX_RESOURCE_FILES}."
    total_chars = sum(len(item.content) for item in files)
    if total_chars > MAX_RESOURCE_CHARS:
        return f"Resource files are too large: {total_chars} chars > {MAX_RESOURCE_CHARS}."
    for item in files:
        try:
            _safe_resource_path(item.path)
        except ValueError as exc:
            return str(exc)
    return ""

def _read_existing_resource_files(root) -> dict[str, str]:
    from nexagent.skills.loader import TEXT_RESOURCE_EXTENSIONS

    result: dict[str, str] = {}
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "SKILL.md":
            continue
        if path.suffix.lower() not in TEXT_RESOURCE_EXTENSIONS:
            continue
        try:
            _safe_resource_path(relative)
        except ValueError:
            continue
        result[relative] = path.read_text(encoding="utf-8", errors="replace")
    return result


def _safe_resource_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise ValueError(f"Invalid resource path: {value}")
    if path.name == "SKILL.md":
        raise ValueError("Resource files may not overwrite SKILL.md.")
    if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
        raise ValueError(f"Hidden or cache paths are not allowed: {value}")
    return path.as_posix()


def _safe_existing_skill_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise ValueError(f"Invalid skill file path: {value}")
    if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
        raise ValueError(f"Hidden or cache paths are not allowed: {value}")
    return path.as_posix()


def _get_skill_lock(skill_id: str) -> asyncio.Lock:
    lock = _SKILL_LOCKS.get(skill_id)
    if lock is None:
        lock = asyncio.Lock()
        _SKILL_LOCKS[skill_id] = lock
    return lock


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _history_file(skill_id: str) -> Path:
    from nexagent.skills.loader import SkillLoader

    history_dir = SkillLoader().public_dir / HISTORY_DIR_NAME
    history_dir.mkdir(parents=True, exist_ok=True)
    return history_dir / f"{skill_id}.jsonl"


def _append_history(skill_id: str, record: dict[str, Any]) -> None:
    payload = {
        "ts": datetime.now(UTC).isoformat(),
        **record,
    }
    path = _history_file(skill_id)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        file.write("\n")


def _read_history(skill_id: str, *, limit: int) -> list[dict[str, Any]]:
    path = _history_file(skill_id)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records[-limit:]


def _scan_skill_text(content: str, *, executable: bool, location: str) -> dict[str, str]:
    """Small local guardrail, not a sandbox. It blocks obvious destructive snippets."""
    lowered = content.lower()
    blocked = [
        "shutil.rmtree",
        "remove-item",
        "rm -rf",
        "del /s",
        "format c:",
        "socket.create_connection",
        "subprocess.popen",
    ]
    if any(token in lowered for token in blocked):
        return {
            "decision": "block",
            "reason": f"{location} contains a high-risk filesystem/process/network pattern.",
        }
    if executable and any(token in lowered for token in ("os.system", "subprocess.run", "eval(", "exec(")):
        return {
            "decision": "warn",
            "reason": f"{location} contains executable patterns that should be reviewed before use.",
        }
    return {"decision": "allow", "reason": ""}


def _text_hash(content: str | None) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _directory_hash(root: Path) -> str:
    hasher = hashlib.sha256()
    if not root.exists():
        return ""
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def _looks_text_path(value: str) -> bool:
    from nexagent.skills.loader import TEXT_RESOURCE_EXTENSIONS

    return PurePosixPath(value).suffix.lower() in TEXT_RESOURCE_EXTENSIONS


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
