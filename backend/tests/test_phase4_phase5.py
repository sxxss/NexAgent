"""Regression tests for Phase 4 and Phase 5 verification scripts."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify_phase4  # noqa: E402
import verify_phase5  # noqa: E402


def test_phase4_frontend_surface() -> None:
    assert verify_phase4.main() == 0


def test_phase5_advanced_backend_surface() -> None:
    asyncio.run(verify_phase5.main_async())
