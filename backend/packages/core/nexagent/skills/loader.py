"""Skill loader — discovers, parses and injects SKILL.md files.

Skills live in  ``<project_root>/skills/public/<skill-name>/SKILL.md``.
Each file may carry a YAML frontmatter block (``---`` delimited) followed
by Markdown content that describes when and how to use the capability.

Typical use
-----------
::

    from nexagent.skills.loader import SkillLoader

    loader = SkillLoader()

    # Discover all available skill names
    names = loader.discover()          # ["knowledge-base", "deep-research", ...]

    # Load all skills
    skills = loader.load_all()

    # Inject selected skills into a system prompt
    prompt = "You are a helpful assistant." + loader.to_system_prompt_blocks(skills)
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nexagent.skills.base import BaseSkill

logger = logging.getLogger(__name__)
SKILL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,63}$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
DEFAULT_MAX_SKILL_PROMPT_CHARS = 4000
DEFAULT_MAX_SKILLS_PROMPT_CHARS = 12000
DEFAULT_MAX_RESOURCE_CHARS = 1200
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
    #: SHA-256 over SKILL.md and optional skill.py content.
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
            "content_hash": self.content_hash,
            "files": self.files,
            "resources": self.resources,
            "validation_issues": [issue.to_dict() for issue in self.validation_issues],
            "content": self.content,
            "path": str(self.path),
            "executable": (self.path.parent / "skill.py").exists(),
        }


# ── Loader ────────────────────────────────────────────────────────────────────

class SkillLoader:
    """Discovers and loads skills from the project's ``skills/`` directory.

    Directory layout expected::

        <project_root>/
        └── skills/
            └── public/
                ├── knowledge-base/
                │   └── SKILL.md
                ├── deep-research/
                │   └── SKILL.md
                └── knowledge-graph/
                    └── SKILL.md

    The default ``skills_dir`` is auto-resolved from the loader file location
    (``backend/packages/core/nexagent/skills/loader.py``) walking up five
    levels to reach the project root, then appending ``skills/``.

    You may override it via:
    - Constructor argument ``skills_dir``
    - ``NEXAGENT_SKILLS_DIR`` environment variable
    - ``skills_dir`` key in ``config.yaml``
    """

    def __init__(self, skills_dir: str | Path | None = None) -> None:
        if skills_dir is None:
            skills_dir = self._resolve_skills_dir()
        self.skills_dir = Path(skills_dir)
        self._cache: dict[str, Skill] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def public_dir(self) -> Path:
        """The ``public/`` sub-directory containing one folder per skill."""
        return self.skills_dir / "public"

    def discover(self) -> list[str]:
        """Return sorted names of all discoverable skills.

        Never raises — returns ``[]`` when the skills directory is absent.
        """
        if not self.public_dir.exists():
            logger.debug("Skills public dir not found: %s", self.public_dir)
            return []
        names = []
        for entry in sorted(self.public_dir.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").exists():
                names.append(entry.name)
        return names

    def load(self, skill_name: str) -> Skill | None:
        """Load and cache a single skill by directory name.

        Returns ``None`` when the skill does not exist or cannot be parsed.
        """
        if skill_name in self._cache:
            return self._cache[skill_name]

        skill_path = self.public_dir / skill_name / "SKILL.md"
        if not skill_path.exists():
            logger.debug("Skill not found: %s", skill_path)
            return None

        try:
            skill = self._parse(skill_name, skill_path)
            self._cache[skill_name] = skill
            logger.debug("Loaded skill '%s' v%s from %s", skill.name, skill.version, skill_path)
            return skill
        except Exception as exc:
            logger.warning("Failed to load skill '%s': %s", skill_name, exc)
            return None

    def load_all(self) -> list[Skill]:
        """Load every discoverable skill and return them in alphabetical order."""
        return [s for name in self.discover() if (s := self.load(name)) is not None]

    def load_selected(self, names: list[str]) -> list[Skill]:
        """Load a specific subset of skills, silently skipping unknown ones."""
        return [s for name in names if (s := self.load(name)) is not None]

    def load_executable(self, skill_name: str) -> BaseSkill | None:
        """Load ``skill.py`` from a skill directory if it defines a BaseSkill subclass."""
        skill_py = self.public_dir / skill_name / "skill.py"
        if not skill_py.exists():
            return None

        module_name = f"nexagent_user_skill_{skill_name.replace('-', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, skill_py)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            logger.warning("Failed to import executable skill '%s': %s", skill_name, exc)
            return None

        for value in module.__dict__.values():
            if isinstance(value, type) and issubclass(value, BaseSkill) and value is not BaseSkill:
                try:
                    return value()
                except Exception as exc:
                    logger.warning("Failed to instantiate executable skill '%s': %s", skill_name, exc)
                    return None
        return None

    def load_executable_tools(self, names: list[str]) -> list:
        """Load LangChain tools exposed by selected executable skills."""
        tools = []
        for name in names:
            skill = self.load_executable(name)
            if skill is not None:
                tools.extend(skill.get_tools())
        return tools

    def reload(self) -> None:
        """Clear the cache so all skills are re-read from disk on next access."""
        self._cache.clear()

    # ── Prompt injection ──────────────────────────────────────────────────────

    def to_system_prompt_blocks(
        self,
        skills: list[Skill],
        *,
        max_chars_per_skill: int = DEFAULT_MAX_SKILL_PROMPT_CHARS,
        max_total_chars: int = DEFAULT_MAX_SKILLS_PROMPT_CHARS,
    ) -> str:
        """Format a list of skills as a system-prompt appendix.

        Returns an empty string when ``skills`` is empty so callers can
        safely concatenate without a conditional::

            prompt = base_prompt + loader.to_system_prompt_blocks(loaded)
        """
        if not skills:
            return ""

        sections: list[str] = [
            "\n\n---",
            "## Specialised Capabilities",
            "You have been equipped with the following skills. "
            "Use them when the user's request matches the described scenarios.\n",
        ]
        used_chars = 0
        for skill in sorted(skills, key=lambda item: item.id):
            remaining_total = max_total_chars - used_chars
            if remaining_total <= 0:
                sections.append("Additional selected skills were omitted because the skill prompt budget was reached.")
                break
            content = skill.content
            limit = min(max_chars_per_skill, remaining_total)
            if len(content) > limit:
                content = content[:limit].rstrip() + "\n\n[Skill content truncated by prompt budget.]"
            sections.append(f"### {skill.name}")
            sections.append(
                f"Skill metadata: id={skill.id}; version={skill.version}; hash={skill.content_hash[:12]}"
            )
            if skill.description:
                sections.append(f"*{skill.description}*\n")
            sections.append(content)
            resource_block = _format_skill_resources(skill.resources, max_chars=DEFAULT_MAX_RESOURCE_CHARS)
            if resource_block:
                sections.append(resource_block)
            sections.append("")   # blank line between skills
            used_chars += len(content) + len(resource_block)

        return "\n".join(sections)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _resolve_skills_dir() -> Path:
        """Auto-resolve the skills directory from environment, config, or path."""
        import os

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

    def _parse(self, dir_name: str, path: Path) -> Skill:
        """Read and parse a SKILL.md file, separating frontmatter from body."""
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
                body = parts[2].strip()

        # Description: prefer frontmatter, then first non-heading paragraph line
        description: str = str(frontmatter.get("description", ""))
        if not description:
            for line in body.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    description = line
                    break

        return Skill(
            id=str(frontmatter.get("id", dir_name)),
            name=str(frontmatter.get("name", dir_name)),
            description=description,
            version=str(frontmatter.get("version", "0.1.0")),
            content=body,
            tags=_string_list(frontmatter.get("tags", [])),
            required_mcp_ids=_string_list(frontmatter.get("required_mcp_ids", [])),
            required_tools=_string_list(frontmatter.get("required_tools", [])),
            content_hash=_content_hash(path),
            files=_scan_skill_files(path.parent),
            resources=_load_text_resources(path.parent),
            validation_issues=_validate_skill_metadata(dir_name, frontmatter, description, body),
            frontmatter=frontmatter,
            path=path,
        )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]


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
            "kind": "entry" if rel == "SKILL.md" else "executable" if rel == "skill.py" else "resource",
            "text": _is_text_resource(path),
        })
    return result


def _load_text_resources(root: Path) -> list[dict[str, str]]:
    resources: list[dict[str, str]] = []
    for path in _iter_skill_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in {"SKILL.md", "skill.py"} or not _is_text_resource(path):
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
) -> list[SkillIssue]:
    issues: list[SkillIssue] = []
    skill_id = str(frontmatter.get("id", dir_name))
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
    for key in ("tags", "required_mcp_ids", "required_tools"):
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
