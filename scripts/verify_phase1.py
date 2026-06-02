"""Verify Phase 1 project skeleton and FastAPI gateway startup."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
CORE_DIR = BACKEND_DIR / "packages" / "core"


def _configure_imports() -> None:
    for path in (BACKEND_DIR, CORE_DIR):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def _ok(message: str) -> None:
    print(f"[ok] {message}")


def _fail(message: str) -> None:
    raise AssertionError(message)


def _require_file(path: Path) -> None:
    if not path.is_file():
        _fail(f"Missing required file: {path.relative_to(PROJECT_ROOT)}")
    _ok(f"found {path.relative_to(PROJECT_ROOT)}")


def _require_dir(path: Path) -> None:
    if not path.is_dir():
        _fail(f"Missing required directory: {path.relative_to(PROJECT_ROOT)}")
    _ok(f"found {path.relative_to(PROJECT_ROOT)}")


def verify_files() -> None:
    required_dirs = [
        BACKEND_DIR,
        CORE_DIR / "nexagent",
        BACKEND_DIR / "app" / "gateway",
        PROJECT_ROOT / "skills" / "public",
    ]
    required_files = [
        PROJECT_ROOT / ".env.example",
        PROJECT_ROOT / ".gitignore",
        PROJECT_ROOT / "Makefile",
        PROJECT_ROOT / "docker-compose.yml",
        BACKEND_DIR / "pyproject.toml",
        BACKEND_DIR / "langgraph.json",
        BACKEND_DIR / "app" / "gateway" / "app.py",
        CORE_DIR / "pyproject.toml",
        CORE_DIR / "nexagent" / "__init__.py",
    ]

    for path in required_dirs:
        _require_dir(path)
    for path in required_files:
        _require_file(path)


def verify_langgraph_config() -> None:
    path = BACKEND_DIR / "langgraph.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if "graphs" not in data:
        _fail("langgraph.json must define a 'graphs' object")
    _ok("langgraph.json is valid JSON and defines graphs")


def verify_gateway() -> None:
    _configure_imports()
    from fastapi.testclient import TestClient

    from app.gateway.app import app

    client = TestClient(app)
    response = client.get("/health")
    if response.status_code != 200:
        _fail(f"GET /health returned {response.status_code}")
    payload = response.json()
    if payload.get("status") != "ok" or payload.get("service") != "nexagent-gateway":
        _fail(f"Unexpected /health payload: {payload}")
    _ok("GET /health returns 200")

    response = client.get("/health/ready")
    if response.status_code != 200:
        _fail(f"GET /health/ready returned {response.status_code}")
    _ok("GET /health/ready returns 200")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Reserved for compatibility; this verifier only checks compose files.",
    )
    parser.parse_args()

    verify_files()
    verify_langgraph_config()
    verify_gateway()
    print("Phase 1 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
