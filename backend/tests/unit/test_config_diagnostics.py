from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


def _work_dir(name: str) -> Path:
    path = (
        Path(__file__).resolve().parents[2]
        / ".test-artifacts"
        / "unit-config-diagnostics"
        / f"{name}-{uuid.uuid4()}"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.unit
def test_config_diagnostics_reports_missing_model_api_key(monkeypatch):
    from nexagent.config import get_config_diagnostics, reset_config_cache

    monkeypatch.delenv("MISSING_MODEL_KEY", raising=False)
    work_dir = _work_dir("missing-key")
    try:
        config_path = work_dir / "config.yaml"
        config_path.write_text(
            """
default_model: demo
models:
  - name: demo
    display_name: Demo
    provider: openai
    model: demo-model
    api_key: $MISSING_MODEL_KEY
sandbox:
  enabled: true
  provider: local
  allow_bash: true
""",
            encoding="utf-8",
        )

        reset_config_cache()
        diagnostics = get_config_diagnostics(config_path)
        reset_config_cache()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    codes = {issue.code for issue in diagnostics.issues}
    assert diagnostics.status == "warning"
    assert "model_api_key_missing" in codes
    assert "local_bash_enabled" in codes


@pytest.mark.unit
def test_config_diagnostics_reports_invalid_default_model():
    from nexagent.config import get_config_diagnostics, reset_config_cache

    work_dir = _work_dir("bad-default")
    try:
        config_path = work_dir / "config.yaml"
        config_path.write_text(
            """
default_model: missing
models:
  - name: demo
    display_name: Demo
    provider: ollama
    model: llama3
sandbox:
  provider: local
  allow_bash: false
""",
            encoding="utf-8",
        )

        reset_config_cache()
        diagnostics = get_config_diagnostics(config_path)
        reset_config_cache()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    assert diagnostics.status == "error"
    assert any(issue.code == "default_model_missing" for issue in diagnostics.issues)
