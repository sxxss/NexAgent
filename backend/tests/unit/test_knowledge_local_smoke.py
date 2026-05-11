from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_shadow_rag_smoke_create_parse_index_search_eval(monkeypatch):
    from nexagent.knowledge.manager import reset_manager
    from nexagent.knowledge.search_service import structured_retrieve
    from nexagent.services import eval_service

    work_dir = Path("test-artifacts") / "local-smoke" / str(uuid.uuid4())
    eval_dir = Path("test-artifacts") / "local-smoke-evals" / str(uuid.uuid4())
    monkeypatch.setenv("NEXAGENT_FORCE_LOCAL_KB_FALLBACK", "1")
    monkeypatch.setattr(eval_service, "_EVAL_DIR", eval_dir)
    manager = reset_manager(str(work_dir))

    kb = await manager.create_kb(name="kb", kb_type="milvus", chunk_preset_id="general")
    file_meta = await manager.add_file(kb.kb_id, "guide.txt", b"Alpha retrieval works in the local shadow index.")
    parsed = await manager.parse_file(kb.kb_id, file_meta.file_id)
    indexed = await manager.index_file(kb.kb_id, parsed.file_id)

    assert indexed.status.value == "indexed"
    search_result = await structured_retrieve(
        query="Alpha retrieval",
        kb_ids=[kb.kb_id],
        mode="keyword",
        top_k=3,
    )
    assert search_result.chunks
    gold_chunk_id = search_result.chunks[0].metadata["chunk_id"]

    suite = eval_service.create_suite(
        name="local smoke",
        type="rag",
        kb_ids=[kb.kb_id],
        samples=[{"query": "What works?", "gold_chunk_ids": [gold_chunk_id]}],
    )
    result = await eval_service.run_suite(suite["id"])

    assert result["passed"] == 1
    assert result["sample_results"][0]["metrics"]["recall@1"] == 1.0
    reset_manager()
    shutil.rmtree(work_dir, ignore_errors=True)
    shutil.rmtree(eval_dir, ignore_errors=True)
