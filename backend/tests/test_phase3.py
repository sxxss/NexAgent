"""Regression test for Phase 3 knowledge workflows."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify_phase3  # noqa: E402


def test_phase3_knowledge_workflows() -> None:
    asyncio.run(verify_phase3.main_async())
