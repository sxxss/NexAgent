"""Verify Phase 4 frontend workbench routes and API client coverage."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = PROJECT_ROOT / "frontend"


def _ok(message: str) -> None:
    print(f"[ok] {message}")


def _fail(message: str) -> None:
    raise AssertionError(message)


def _require_file(path: Path) -> None:
    if not path.is_file():
        _fail(f"Missing required file: {path.relative_to(PROJECT_ROOT)}")
    _ok(f"found {path.relative_to(PROJECT_ROOT)}")


def main() -> int:
    required_pages = [
        "src/app/page.tsx",
        "src/app/research/page.tsx",
        "src/app/knowledge/page.tsx",
        "src/app/knowledge/[id]/page.tsx",
        "src/app/dashboard/page.tsx",
        "src/app/agents/page.tsx",
        "src/app/skills/page.tsx",
        "src/app/channels/page.tsx",
        "src/app/settings/page.tsx",
        "src/app/eval/page.tsx",
    ]
    for rel in required_pages:
        _require_file(FRONTEND / rel)

    api_text = (FRONTEND / "src/lib/api.ts").read_text(encoding="utf-8")
    for symbol in (
        "fetchKnowledgeGraph",
        "uploadGraph",
        "fetchAgents",
        "fetchSkills",
        "fetchChannels",
        "sendChannelMessage",
        "fetchSystemInfo",
    ):
        if symbol not in api_text:
            _fail(f"API client missing {symbol}")
    _ok("frontend API client covers Phase 4 routes")

    sidebar = (FRONTEND / "src/components/Sidebar.tsx").read_text(encoding="utf-8")
    for href in ("/dashboard", "/agents", "/skills", "/channels", "/settings", "/eval"):
        if href not in sidebar:
            _fail(f"Sidebar missing navigation target {href}")
    _ok("sidebar exposes Phase 4/5 workbench navigation")

    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    for script in ("lint", "build", "dev"):
        if script not in package.get("scripts", {}):
            _fail(f"frontend package.json missing script: {script}")
    _ok("frontend scripts are present")
    print("Phase 4 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
