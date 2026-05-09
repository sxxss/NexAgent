from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


def _work_dir() -> Path:
    path = Path(__file__).resolve().parents[2] / ".test-artifacts" / "unit-artifacts" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.unit
def test_thread_artifacts_are_listed_and_previewed(monkeypatch):
    from nexagent.config import reset_config_cache

    work_dir = _work_dir()
    try:
        config_path = work_dir / "config.yaml"
        sandbox_root = work_dir / "sandbox"
        config_path.write_text(
            f"""
default_model: demo
models:
  - name: demo
    display_name: Demo
    provider: ollama
    model: llama3
sandbox:
  provider: local
  local:
    base_dir: {sandbox_root.as_posix()}
  allow_bash: false
""",
            encoding="utf-8",
        )
        monkeypatch.setenv("NEXAGENT_CONFIG_PATH", str(config_path))
        reset_config_cache()

        from nexagent.sandbox.sandbox import VirtualPathTranslator

        translator = VirtualPathTranslator(sandbox_root)
        real = translator.to_real("/mnt/user-data/outputs/report.md", "thread-a")
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text("# Report\n\nhello", encoding="utf-8")

        from nexagent.artifacts import list_thread_artifacts, read_artifact_preview, resolve_artifact

        artifacts = list_thread_artifacts("thread-a")
        assert [item.path for item in artifacts] == ["/mnt/user-data/outputs/report.md"]
        assert artifacts[0].previewable is True
        assert resolve_artifact("thread-a", "/mnt/user-data/outputs/report.md") == real.resolve()
        preview = read_artifact_preview("thread-a", "/mnt/user-data/outputs/report.md")
        assert preview["content"].startswith("# Report")
    finally:
        reset_config_cache()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_artifact_resolver_rejects_non_output_paths(monkeypatch):
    from nexagent.config import reset_config_cache

    work_dir = _work_dir()
    try:
        config_path = work_dir / "config.yaml"
        sandbox_root = work_dir / "sandbox"
        config_path.write_text(
            f"""
default_model: demo
models:
  - name: demo
    display_name: Demo
    provider: ollama
    model: llama3
sandbox:
  provider: local
  local:
    base_dir: {sandbox_root.as_posix()}
  allow_bash: false
""",
            encoding="utf-8",
        )
        monkeypatch.setenv("NEXAGENT_CONFIG_PATH", str(config_path))
        reset_config_cache()

        from nexagent.artifacts import resolve_artifact

        with pytest.raises(ValueError):
            resolve_artifact("thread-a", "/mnt/user-data/workspace/notes.txt")
    finally:
        reset_config_cache()
        shutil.rmtree(work_dir, ignore_errors=True)
