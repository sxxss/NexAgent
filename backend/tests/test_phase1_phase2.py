"""Regression tests for Phase 1 and Phase 2 completion checks."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify_phase1  # noqa: E402
import verify_phase2  # noqa: E402


def test_phase1_gateway_skeleton() -> None:
    verify_phase1.verify_files()
    verify_phase1.verify_langgraph_config()
    verify_phase1.verify_gateway()


def test_phase2_agent_engine() -> None:
    verify_phase2._configure_runtime()
    verify_dir = PROJECT_ROOT / ".nexagent" / "pytest_phase2"
    verify_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NEXAGENT_DATA_DIR"] = str(verify_dir)

    verify_phase2.verify_registry()
    verify_phase2.verify_context_and_models()
    verify_phase2.verify_tools_and_skills()
    asyncio.run(verify_phase2.verify_chat_service())
    verify_phase2.verify_http_routes()
