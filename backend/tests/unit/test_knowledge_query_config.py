from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_query_config_modes_are_scoped_by_kb_type():
    from nexagent.knowledge.manager import KnowledgeBaseManager
    from nexagent.knowledge.models import KBType

    work_dir = _fresh_dir("query-config")
    manager = KnowledgeBaseManager(str(work_dir))
    milvus = await manager.create_kb(name="milvus", kb_type=KBType.MILVUS.value)
    lightrag = await manager.create_kb(name="light", kb_type=KBType.LIGHTRAG.value)

    manager.update_query_config(milvus.kb_id, {"mode": "lightrag_local", "bm25_weight": 0.4})
    manager.update_query_config(lightrag.kb_id, {"mode": "keyword", "bm25_weight": 0.4})

    milvus_config = manager.get_query_config(milvus.kb_id)
    light_config = manager.get_query_config(lightrag.kb_id)

    assert milvus_config["mode"] == "hybrid"
    assert milvus_config["search_mode"] == "hybrid"
    assert milvus_config["bm25_weight"] == 0.4
    assert light_config["mode"] == "lightrag_hybrid"
    assert light_config["search_mode"] == "lightrag_hybrid"
    assert "bm25_weight" not in light_config
    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_query_config_options_hide_unsupported_modes():
    from nexagent.knowledge.manager import KnowledgeBaseManager
    from nexagent.knowledge.models import KBType

    work_dir = _fresh_dir("query-options")
    manager = KnowledgeBaseManager(str(work_dir))
    milvus = await manager.create_kb(name="milvus", kb_type=KBType.MILVUS.value)
    lightrag = await manager.create_kb(name="light", kb_type=KBType.LIGHTRAG.value)

    milvus_modes = _search_mode_values(manager.get_query_options(milvus.kb_id))
    light_modes = _search_mode_values(manager.get_query_options(lightrag.kb_id))
    light_keys = {item["key"] for item in manager.get_query_options(lightrag.kb_id)}

    assert milvus_modes == {"vector", "keyword", "hybrid"}
    assert light_modes == {"lightrag_local", "lightrag_global", "lightrag_hybrid"}
    assert "bm25_weight" not in light_keys
    shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
def test_milvus_list_indexed_chunks_prefers_local_index():
    from nexagent.knowledge.implementations.milvus_kb import MilvusKB
    from nexagent.knowledge.models import KBMeta, KBType

    kb = KBMeta(kb_id=str(uuid.uuid4()), name="kb", kb_type=KBType.MILVUS)
    work_dir = _fresh_dir("indexed-chunks")
    backend = MilvusKB(work_dir)
    backend._save_local_index(
        kb,
        {"chunks": [{"file_id": "f1", "filename": "doc.md", "chunk_index": 2, "content": "alpha beta"}]},
    )

    chunks = backend.list_indexed_chunks(kb, limit=10)

    assert chunks == [
        {
            "id": "f1:2",
            "chunk_id": "f1:2",
            "content": "alpha beta",
            "file_id": "f1",
            "filename": "doc.md",
            "chunk_index": 2,
            "source": "local_index",
            "metadata": {"source": "doc.md"},
        }
    ]
    shutil.rmtree(work_dir, ignore_errors=True)


def _search_mode_values(options: list[dict]) -> set[str]:
    for option in options:
        if option.get("key") == "search_mode":
            return {item["value"] for item in option["options"]}
    return set()


def _fresh_dir(name: str) -> Path:
    path = Path("test-artifacts") / name / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path
