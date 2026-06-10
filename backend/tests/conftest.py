"""Shared pytest configuration for layered NexAgent tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
CORE_DIR = BACKEND_DIR / "packages" / "core"

for path in (BACKEND_DIR, CORE_DIR):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: fast tests with no external services")
    config.addinivalue_line("markers", "integration: tests that need database or vector/graph services")
    config.addinivalue_line("markers", "e2e: full workflow tests")
    config.addinivalue_line("markers", "slow: tests that take more than 30 seconds")


@pytest.fixture(autouse=True)
def _restore_environ():
    """Snapshot and restore ``os.environ`` around every test.

    Some ``verify_*`` smoke scripts mutate the process environment directly
    (e.g. ``NEXAGENT_FORCE_LOCAL_KB_FALLBACK``) instead of using monkeypatch,
    which would otherwise leak into and pollute later unit tests.
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
