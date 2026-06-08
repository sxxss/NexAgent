"""Skill loader — discovers, parses and advertises SKILL.md files.

Skills live in directories containing a required ``SKILL.md`` file.  NexAgent
ships built-ins in ``<project_root>/skills/public`` and installs user/community
packages in ``<project_root>/skills/custom``.  Additional roots can be supplied
through config or environment variables so packages from Claude Code, Codex,
Copilot, and the open ``SKILL.md`` ecosystem can be reused without rewriting
them.

Typical use
-----------
::

    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()

    # Discover all available skill names
    names = loader.discover()          # ["knowledge-base", "deep-research", ...]

    # Load all skills
    skills = loader.load_all()

    # Advertise selected skills in a system prompt
    prompt = "You are a helpful assistant." + loader.to_system_prompt_blocks(skills)
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)
SKILL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
DEFAULT_MAX_SKILL_PROMPT_CHARS = 4000
DEFAULT_MAX_SKILLS_PROMPT_CHARS = 12000
DEFAULT_MAX_RESOURCE_CHARS = 1200
STATE_FILE_NAME = "state.json"
STANDARD_SKILL_CATEGORIES = ("public", "custom")
TEXT_RESOURCE_EXTENSIONS = {
    ".csv",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sql",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
STANDARD_SKILLS_ROOT = "/mnt/skills"
COMPATIBLE_SKILLS_ROOTS = (
    "/mnt/skills/public",
    "/mnt/skills/custom",
)
CLAUDE_TOOL_ALIASES = {
    "Bash": "bash",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "str_replace",
    "MultiEdit": "str_replace",
    "Grep": "grep",
    "Glob": "glob",
    "WebFetch": "web_fetch",
    "WebSearch": "web_search",
    "Task": "delegate_subagents",
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class SkillIssue:
    """Validation or dependency issue attached to a skill."""

    severity: str
    code: str
    message: str
    fix: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class Skill:
    """A fully loaded and parsed skill definition."""

    #: Stable id, matching the directory name unless frontmatter explicitly sets it.
    id: str
    #: Canonical name (from frontmatter ``name`` key, or directory name)
    name: str
    #: One-line human-readable description
    description: str
    #: Semver string from frontmatter, default ``"0.1.0"``
    version: str
    #: Markdown body (frontmatter stripped)
    content: str
    #: Tags used for filtering and install hints.
    tags: list[str] = field(default_factory=list)
    #: MCP server ids this skill expects at runtime.
    required_mcp_ids: list[str] = field(default_factory=list)
    #: Tool names this skill expects at runtime.
    required_tools: list[str] = field(default_factory=list)
    #: Other Skills that should be made visible when this Skill is selected.
    skill_dependencies: list[str] = field(default_factory=list)
    #: Claude/Copilot style tool allowlist. This is a permission hint, not a dependency.
    allowed_tools: list[str] = field(default_factory=list)
    #: Source category such as ``public``, ``custom`` or ``external``.
    category: str = "public"
    #: Whether the Skill is enabled for default prompt discovery.
    enabled: bool = True
    #: Root the Skill was discovered under.
    source_root: Path = field(default_factory=Path)
    #: Directory path relative to ``source_root/category`` (or source root for external).
    relative_dir: str = ""
    #: Names that can be used to select this Skill.
    aliases: list[str] = field(default_factory=list)
    #: Primary runtime path exposed to the model.
    runtime_path: str = ""
    #: Compatibility runtime paths for category-aware skill packages.
    runtime_paths: list[str] = field(default_factory=list)
    #: SHA-256 over SKILL.md and bundled resource content.
    content_hash: str = ""
    #: Files packaged with this skill, relative to the skill directory.
    files: list[dict[str, Any]] = field(default_factory=list)
    #: Text resources loaded from supporting files, capped for prompt safety.
    resources: list[dict[str, str]] = field(default_factory=list)
    #: Static metadata validation issues.
    validation_issues: list[SkillIssue] = field(default_factory=list)
    #: Raw parsed frontmatter dict
    frontmatter: dict[str, Any] = field(default_factory=dict)
    #: Filesystem path to the SKILL.md file
    path: Path = field(default_factory=Path)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
            "required_mcp_ids": self.required_mcp_ids,
            "required_tools": self.required_tools,
            "skill_dependencies": self.skill_dependencies,
            "allowed_tools": self.allowed_tools,
            "category": self.category,
            "enabled": self.enabled,
            "source_root": str(self.source_root) if self.source_root else "",
            "relative_dir": self.relative_dir,
            "aliases": self.aliases,
            "runtime_path": self.runtime_path,
            "runtime_paths": self.runtime_paths,
            "content_hash": self.content_hash,
            "files": self.files,
            "resources": self.resources,
            "validation_issues": [issue.to_dict() for issue in self.validation_issues],
            "content": self.content,
            "path": str(self.path),
        }


# ── Loader ────────────────────────────────────────────────────────────────────

class SkillLoader:
    """Discovers and loads skills from the project's ``skills/`` directory.

    Directory layout expected::

        <project_root>/
        └── skills/
            ├── public/
                ├── knowledge-base/
                │   └── SKILL.md
            └── custom/
                └── community-skill/
                    └── SKILL.md

    The default ``skills_dir`` is auto-resolved from the loader file location
    (``backend/packages/core/nexagent/skills/loader.py``) walking up five
    levels to reach the project root, then appending ``skills/``.

    You may override it via:
    - Constructor argument ``skills_dir``
    - ``NEXAGENT_SKILLS_DIR`` environment variable
    - ``skills_dir`` key in ``config.yaml``
    """

    def __init__(self, skills_dir: str | Path | None = None, extra_dirs: list[str | Path] | None = None) -> None:
        if skills_dir is None:
            skills_dir = self._resolve_skills_dir()
        self.skills_dir = Path(skills_dir)
        self._cache: dict[str, Skill] = {}
        self._index: dict[str, _SkillLocation] | None = None
        configured_extra_dirs = self._resolve_extra_dirs() if extra_dirs is None else extra_dirs
        self.extra_dirs = [Path(item) for item in configured_extra_dirs if str(item)]

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def public_dir(self) -> Path:
        """The ``public/`` sub-directory containing one folder per skill."""
        return self.skills_dir / "public"

    @property
    def custom_dir(self) -> Path:
        """The ``custom/`` sub-directory for user-installed and community skills."""
        return self.skills_dir / "custom"

    @property
    def state_path(self) -> Path:
        """Optional local state file storing enabled/disabled flags."""
        return self.skills_dir / STATE_FILE_NAME

    def discover(self) -> list[str]:
        """Return sorted names of all discoverable skills.

        Never raises — returns ``[]`` when the skills directory is absent.
        """
        return sorted({location.skill_id for location in self._locations().values()})

    def load(self, skill_name: str) -> Skill | None:
        """Load and cache a single skill by directory name.

        Returns ``None`` when the skill does not exist or cannot be parsed.
        """
        lookup_key = self._lookup_key(skill_name)
        if lookup_key in self._cache:
            return self._cache[lookup_key]

        location = self._locations().get(lookup_key)
        if location is None:
            logger.debug("Skill not found: %s", skill_name)
            return None

        try:
            skill = self._parse(location)
            for alias in skill.aliases:
                self._cache[self._lookup_key(alias)] = skill
            logger.debug("Loaded skill '%s' v%s from %s", skill.name, skill.version, location.skill_file)
            return skill
        except Exception as exc:
            logger.warning("Failed to load skill '%s': %s", skill_name, exc)
            return None

    def load_all(self) -> list[Skill]:
        """Load every discoverable skill and return them in alphabetical order."""
        return [s for name in self.discover() if (s := self.load(name)) is not None]

    def load_enabled(self) -> list[Skill]:
        """Load all Skills enabled for default prompt discovery."""
        return [skill for skill in self.load_all() if skill.enabled]

    def load_selected(self, names: list[str]) -> list[Skill]:
        """Load a specific subset of skills, silently skipping unknown ones."""
        return [s for name in names if (s := self.load(name)) is not None]

    def reload(self) -> None:
        """Clear the cache so all skills are re-read from disk on next access."""
        self._cache.clear()
        self._index = None

    # ── Prompt injection ──────────────────────────────────────────────────────

    def to_system_prompt_blocks(
        self,
        skills: list[Skill],
        *,
        max_chars_per_skill: int = DEFAULT_MAX_SKILL_PROMPT_CHARS,
        max_total_chars: int = DEFAULT_MAX_SKILLS_PROMPT_CHARS,
    ) -> str:
        """Format selected skills as a progressive-loading prompt appendix.

        The prompt intentionally contains only metadata and the sandbox path to
        each ``SKILL.md``. The model should read the skill file only after a user
        request matches the skill's trigger, then read referenced resources on
        demand.
        """
        if not skills:
            return ""

        sections: list[str] = [
            "\n\n## Skills System",
            "You have access to Skills that provide specialized workflows and supporting files.",
            "",
            "**Available Skills:**",
        ]
        for skill in sorted(skills, key=lambda item: item.id):
            skill_id = html.escape(skill.id)
            name = html.escape(skill.name)
            description = html.escape(skill.description)
            runtime_path = html.escape(skill.runtime_path or f"{STANDARD_SKILLS_ROOT}/{skill.id}")
            sections.append(
                f"- **{name}** (`{skill_id}`): {description}\n"
                f"  -> Read `{runtime_path}/SKILL.md`"
            )
        sections.extend([
            "",
            "**How to Use Skills:**",
            "1. Identify whether the user's request matches a Skill description.",
            "2. If a Skill applies, read its full `SKILL.md` from the path shown above. There is no "
            "separate activation mechanism.",
            "3. Follow the instructions in `SKILL.md` exactly.",
            "4. Access supporting files only when the Skill instructions call for them. Use absolute paths "
            f"under `{STANDARD_SKILLS_ROOT}/<skill-id>/`, such as "
            f"`{STANDARD_SKILLS_ROOT}/<skill-id>/references/example.md`.",
            "5. Execute bundled scripts as ordinary files with bash, using absolute paths such as "
            f"`python {STANDARD_SKILLS_ROOT}/<skill-id>/scripts/example.py`.",
            f"6. Treat everything under `{STANDARD_SKILLS_ROOT}` as read-only runtime material.",
            "7. Some imported Skills mention category paths like `/mnt/skills/public/<skill-id>` or "
            "`/mnt/skills/custom/<skill-id>`; those are compatibility aliases for the same read-only runtime files.",
            "",
            "Skill bodies and supporting resources are loaded progressively; do not load files that are not "
            "needed for the current task.",
        ])

        return "\n".join(sections)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _resolve_skills_dir() -> Path:
        """Auto-resolve the skills directory from environment, config, or path."""
        # 1. Explicit env var
        env_dir = os.environ.get("NEXAGENT_SKILLS_DIR")
        if env_dir:
            return Path(env_dir)

        # 2. config.yaml ``skills_dir`` key
        try:
            from nexagent.config import get_config
            cfg_dir = get_config().skills_dir
            if cfg_dir:
                return Path(cfg_dir)
        except Exception:
            pass

        # 3. Walk up from loader.py to project root
        #    loader.py → nexagent/skills/ → nexagent/ → core/ → packages/ → backend/ → NexAgent/
        #                 [0]               [1]          [2]      [3]          [4]        [5]
        return Path(__file__).parents[5] / "skills"

    @staticmethod
    def _resolve_extra_dirs() -> list[Path]:
        values: list[str] = []
        env_value = os.environ.get("NEXAGENT_SKILLS_EXTRA_DIRS", "")
        if env_value:
            values.extend(part for part in env_value.split(os.pathsep) if part.strip())
        try:
            from nexagent.config import get_config

            for item in getattr(get_config(), "skills_extra_dirs", []) or []:
                if item:
                    values.append(str(item))
        except Exception:
            pass
        return [Path(item).expanduser() for item in values]

    def _locations(self) -> dict[str, _SkillLocation]:
        if self._index is not None:
            return self._index

        state = _load_state(self.state_path)
        ordered_locations: list[_SkillLocation] = []
        for category in STANDARD_SKILL_CATEGORIES:
            category_root = self.skills_dir / category
            ordered_locations.extend(
                _scan_skill_locations(category_root, category=category, source_root=self.skills_dir)
            )
        for extra_dir in self.extra_dirs:
            ordered_locations.extend(
                _scan_external_skill_locations(extra_dir, source_root=extra_dir)
            )

        index: dict[str, _SkillLocation] = {}
        for location in ordered_locations:
            enabled = _is_enabled(location, state)
            location.enabled = enabled
            for alias in location.aliases:
                index[self._lookup_key(alias)] = location
        self._index = index
        return index

    @staticmethod
    def _lookup_key(value: str) -> str:
        return str(value or "").strip().lower()

    def _parse(self, location: _SkillLocation) -> Skill:
        """Read and parse a SKILL.md file, separating frontmatter from body."""
        dir_name = location.skill_dir.name
        path = location.skill_file
        raw = path.read_text(encoding="utf-8")

        frontmatter: dict[str, Any] = {}
        body: str = raw

        # YAML frontmatter block: starts and ends with ``---``
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError as exc:
                    logger.warning("YAML parse error in '%s': %s", path, exc)
                    frontmatter = {}
                if not isinstance(frontmatter, dict):
                    frontmatter = {}
                body = parts[2].strip()

        # Description: prefer frontmatter, then first non-heading paragraph line
        description: str = str(frontmatter.get("description", ""))
        if not description:
            for line in body.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    description = line
                    break

        skill_id = str(frontmatter.get("id") or frontmatter.get("name") or dir_name).strip() or dir_name
        name = str(frontmatter.get("name", skill_id)).strip() or skill_id
        aliases = _skill_aliases(skill_id, name, location)
        runtime_path = f"{STANDARD_SKILLS_ROOT}/{skill_id}"
        runtime_paths = [runtime_path]
        if location.category in STANDARD_SKILL_CATEGORIES:
            runtime_paths.append(f"{STANDARD_SKILLS_ROOT}/{location.category}/{skill_id}")
        return Skill(
            id=skill_id,
            name=name,
            description=description,
            version=str(frontmatter.get("version", "0.1.0")),
            content=body,
            tags=_string_list(frontmatter.get("tags", [])),
            required_mcp_ids=_combined_string_list(
                frontmatter.get("required_mcp_ids", []),
                frontmatter.get("mcp_dependencies", []),
            ),
            required_tools=_combined_tool_list(
                frontmatter.get("required_tools", []),
                frontmatter.get("tool_dependencies", []),
            ),
            skill_dependencies=_combined_string_list(frontmatter.get("skill_dependencies", [])),
            allowed_tools=_combined_tool_list(
                frontmatter.get("allowed_tools", []),
                frontmatter.get("allowed-tools", []),
            ),
            category=location.category,
            enabled=location.enabled,
            source_root=location.source_root,
            relative_dir=location.relative_dir,
            aliases=aliases,
            runtime_path=runtime_path,
            runtime_paths=runtime_paths,
            content_hash=_content_hash(path),
            files=_scan_skill_files(path.parent),
            resources=_load_text_resources(path.parent),
            validation_issues=_validate_skill_metadata(dir_name, frontmatter, description, body, skill_id=skill_id),
            frontmatter=frontmatter,
            path=path,
        )


@dataclass
class _SkillLocation:
    skill_id: str
    aliases: list[str]
    skill_dir: Path
    skill_file: Path
    source_root: Path
    category: str
    relative_dir: str
    enabled: bool = True


def _scan_skill_locations(category_root: Path, *, category: str, source_root: Path) -> list[_SkillLocation]:
    if not category_root.exists() or not category_root.is_dir():
        return []
    locations: list[_SkillLocation] = []
    for skill_file in sorted(category_root.rglob("SKILL.md")):
        if _has_ignored_part(skill_file.relative_to(category_root).parts):
            continue
        skill_dir = skill_file.parent
        try:
            relative_dir = skill_dir.relative_to(category_root).as_posix()
        except ValueError:
            relative_dir = skill_dir.name
        locations.append(_build_location(
            skill_dir=skill_dir,
            skill_file=skill_file,
            category=category,
            source_root=source_root,
            relative_dir=relative_dir,
        ))
    return locations


def _scan_external_skill_locations(root: Path, *, source_root: Path) -> list[_SkillLocation]:
    root = root.expanduser()
    if not root.exists() or not root.is_dir():
        return []

    locations: list[_SkillLocation] = []
    scanned_files: set[Path] = set()
    for category in STANDARD_SKILL_CATEGORIES:
        category_root = root / category
        for location in _scan_skill_locations(category_root, category=category, source_root=source_root):
            scanned_files.add(location.skill_file.resolve())
            locations.append(location)

    for skill_file in sorted(root.rglob("SKILL.md")):
        resolved = skill_file.resolve()
        if resolved in scanned_files:
            continue
        try:
            rel_parts = skill_file.relative_to(root).parts
        except ValueError:
            rel_parts = skill_file.parts
        if _has_ignored_part(rel_parts):
            continue
        skill_dir = skill_file.parent
        relative_dir = skill_dir.relative_to(root).as_posix()
        locations.append(_build_location(
            skill_dir=skill_dir,
            skill_file=skill_file,
            category="external",
            source_root=source_root,
            relative_dir=relative_dir,
        ))
    return locations


def _build_location(
    *,
    skill_dir: Path,
    skill_file: Path,
    category: str,
    source_root: Path,
    relative_dir: str,
) -> _SkillLocation:
    metadata = _read_frontmatter_quiet(skill_file)
    skill_id = str(metadata.get("id") or metadata.get("name") or skill_dir.name).strip() or skill_dir.name
    name = str(metadata.get("name") or skill_id).strip() or skill_id
    aliases = _location_aliases(skill_id, name, skill_dir.name, relative_dir, category)
    return _SkillLocation(
        skill_id=skill_id,
        aliases=aliases,
        skill_dir=skill_dir,
        skill_file=skill_file,
        source_root=source_root,
        category=category,
        relative_dir=relative_dir,
    )


def _read_frontmatter_quiet(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _location_aliases(skill_id: str, name: str, dirname: str, relative_dir: str, category: str) -> list[str]:
    values = [skill_id, name, dirname, relative_dir, Path(relative_dir).name]
    if category in STANDARD_SKILL_CATEGORIES:
        values.extend([f"{category}/{relative_dir}", f"{category}/{skill_id}", f"{category}/{dirname}"])
    return _dedupe_aliases(values)


def _skill_aliases(skill_id: str, name: str, location: _SkillLocation) -> list[str]:
    return _dedupe_aliases([*location.aliases, skill_id, name, location.relative_dir, location.skill_dir.name])


def _dedupe_aliases(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        for alias in (raw, _slug_alias(raw)):
            clean = alias.strip()
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(clean)
    return result


def _slug_alias(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-_").lower()
    return slug[:64].strip("-_")


def _has_ignored_part(parts: tuple[str, ...]) -> bool:
    return any(part.startswith(".") or part == "__pycache__" for part in parts)


def _load_state(path: Path) -> dict[str, Any]:
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _is_enabled(location: _SkillLocation, state: dict[str, Any]) -> bool:
    skills_state = state.get("skills", state)
    if not isinstance(skills_state, dict):
        return True
    for alias in location.aliases:
        item = skills_state.get(alias) or skills_state.get(alias.lower())
        if isinstance(item, bool):
            return item
        if isinstance(item, dict) and "enabled" in item:
            return bool(item.get("enabled"))
    return True


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_string_list(item))
        return result
    return [str(value)]


def _combined_string_list(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _string_list(value):
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
    return result


def _combined_tool_list(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _string_list(value):
            normalized = _normalize_tool_name(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
    return result


def _normalize_tool_name(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    # Claude allows forms such as Bash(git diff:*) in allowed-tools.
    base = raw.split("(", 1)[0].strip()
    return CLAUDE_TOOL_ALIASES.get(base, CLAUDE_TOOL_ALIASES.get(raw, raw))


def _content_hash(skill_path: Path) -> str:
    sha = hashlib.sha256()
    root = skill_path.parent
    for path in _iter_skill_files(root):
        rel = path.relative_to(root).as_posix()
        sha.update(rel.encode("utf-8"))
        sha.update(b"\0")
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                sha.update(chunk)
    return sha.hexdigest()


def _iter_skill_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if rel_parts == ("skill.py",):
            continue
        if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _scan_skill_files(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in _iter_skill_files(root):
        rel = path.relative_to(root).as_posix()
        result.append({
            "path": rel,
            "size": path.stat().st_size,
            "kind": _skill_file_kind(rel),
            "text": _is_text_resource(path),
        })
    return result


def _load_text_resources(root: Path) -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    for path in _iter_skill_files(root):
        rel = path.relative_to(root).as_posix()
        if rel == "SKILL.md" or not _is_text_resource(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if len(text) > DEFAULT_MAX_RESOURCE_CHARS:
            text = text[:DEFAULT_MAX_RESOURCE_CHARS].rstrip() + "\n\n[Resource truncated by prompt budget.]"
        resources.append({"path": rel, "content": text})
    return resources


def _is_text_resource(path: Path) -> bool:
    return path.suffix.lower() in TEXT_RESOURCE_EXTENSIONS


def _skill_file_kind(rel: str) -> str:
    if rel == "SKILL.md":
        return "entry"
    if rel.startswith("scripts/"):
        return "script"
    return "resource"


def _format_skill_resources(resources: list[dict[str, str]], *, max_chars: int) -> str:
    if not resources:
        return ""
    used = 0
    lines = ["#### Supporting resources"]
    for resource in resources:
        path = resource.get("path", "")
        content = resource.get("content", "")
        if not path or not content:
            continue
        remaining = max_chars - used
        if remaining <= 0:
            lines.append("Additional resource content omitted because the resource prompt budget was reached.")
            break
        clipped = content[:remaining].rstrip()
        if len(content) > remaining:
            clipped += "\n\n[Resource truncated by prompt budget.]"
        lines.extend([f"Resource: `{path}`", "```", clipped, "```"])
        used += len(clipped)
    return "\n".join(lines) if len(lines) > 1 else ""


def _validate_skill_metadata(
    dir_name: str,
    frontmatter: dict[str, Any],
    description: str,
    body: str,
    *,
    skill_id: str | None = None,
) -> list[SkillIssue]:
    issues: list[SkillIssue] = []
    skill_id = str(skill_id if skill_id is not None else frontmatter.get("id", dir_name))
    name = str(frontmatter.get("name", dir_name))
    version = str(frontmatter.get("version", "0.1.0"))
    if not SKILL_ID_PATTERN.match(skill_id):
        issues.append(
            SkillIssue(
                "error",
                "invalid_id",
                "Skill id may only contain letters, numbers, '-' and '_'.",
                "Rename the skill folder or set a valid id.",
            )
        )
    if skill_id != dir_name:
        issues.append(
            SkillIssue(
                "warning",
                "id_mismatch",
                "Skill id does not match its folder name.",
                "Keep id and folder name aligned for predictable selection.",
            )
        )
    if not name.strip():
        issues.append(
            SkillIssue("error", "missing_name", "Skill name is required.", "Add name to SKILL.md frontmatter.")
        )
    if not SEMVER_PATTERN.match(version):
        issues.append(
            SkillIssue(
                "warning",
                "invalid_version",
                "Skill version should use semver, for example 0.1.0.",
                "Update version in SKILL.md frontmatter.",
            )
        )
    if not description.strip():
        issues.append(
            SkillIssue("warning", "missing_description", "Skill description is empty.", "Add a one-line description.")
        )
    if not body.strip():
        issues.append(
            SkillIssue(
                "error",
                "empty_prompt",
                "Skill prompt content is empty.",
                "Add instructions below the frontmatter.",
            )
        )
    metadata_list_keys = (
        "tags",
        "required_mcp_ids",
        "required_tools",
        "mcp_dependencies",
        "tool_dependencies",
        "skill_dependencies",
        "allowed_tools",
        "allowed-tools",
    )
    for key in metadata_list_keys:
        value = frontmatter.get(key, [])
        if value is not None and not isinstance(value, (list, str)):
            issues.append(
                SkillIssue(
                    "warning",
                    f"invalid_{key}",
                    f"{key} should be a list of strings.",
                    f"Update {key} in SKILL.md frontmatter.",
                )
            )
    return issues
