from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.unit
def test_config_loader_expands_nested_env_and_migrates(monkeypatch):
    from nexagent.config import load_config, reset_config_cache

    monkeypatch.setenv("TEST_MODEL_KEY", "secret")
    monkeypatch.setenv("TEST_TRACE_KEY", "trace-secret")
    work_dir = Path(__file__).resolve().parents[2] / ".test-artifacts" / "config"
    work_dir.mkdir(parents=True, exist_ok=True)
    config_path = work_dir / "config.yaml"
    config_path.write_text(
        """
default_model: demo
models:
  - name: demo
    display_name: Demo
    provider: fake
    model: fake
    api_key: $TEST_MODEL_KEY
tracing:
  langsmith:
    enabled: false
    api_key: $TEST_TRACE_KEY
sandbox:
  enabled: true
""",
        encoding="utf-8",
    )

    reset_config_cache()
    config = load_config(config_path)
    reset_config_cache()

    assert config.config_version == 2
    assert config.models[0].api_key == "secret"
    assert config.tracing.langsmith.api_key == "trace-secret"
    assert config.sandbox.provider == "local"
    assert config.knowledge.vector_store_enabled is True
    assert config.sandbox.audit_enabled is True
    assert config.sandbox.allow_bash is True


@pytest.mark.unit
def test_config_loader_hot_reloads_when_file_changes(monkeypatch):
    from nexagent.config import load_config, reset_config_cache

    work_dir = Path(__file__).resolve().parents[2] / ".test-artifacts" / "config_reload"
    work_dir.mkdir(parents=True, exist_ok=True)
    config_path = work_dir / "config.yaml"
    config_path.write_text("default_model: first\nmodels: []\n", encoding="utf-8")
    reset_config_cache()

    first = load_config(config_path)
    assert first.default_model == "first"

    config_path.write_text("default_model: second\nmodels: []\n", encoding="utf-8")
    stat = config_path.stat()
    os.utime(config_path, (stat.st_atime + 2, stat.st_mtime + 2))

    second = load_config(config_path)
    reset_config_cache()
    assert second.default_model == "second"


@pytest.mark.unit
def test_config_loader_env_overrides_container_service_hosts(monkeypatch):
    from nexagent.config import load_config, reset_config_cache

    work_dir = Path(__file__).resolve().parents[2] / ".test-artifacts" / "config_env_override"
    work_dir.mkdir(parents=True, exist_ok=True)
    config_path = work_dir / "config.yaml"
    config_path.write_text(
        """
knowledge:
  milvus_host: localhost
  milvus_port: 19530
  neo4j_uri: bolt://localhost:7687
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MILVUS_HOST", "milvus")
    monkeypatch.setenv("MILVUS_PORT", "19531")
    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j:7687")

    reset_config_cache()
    config = load_config(config_path)
    reset_config_cache()

    assert config.knowledge.milvus_host == "milvus"
    assert config.knowledge.milvus_port == 19531
    assert config.knowledge.neo4j_uri == "bolt://neo4j:7687"
