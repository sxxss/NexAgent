from __future__ import annotations

import shutil
import uuid
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from app.gateway.routers import knowledge


def _work_dir(prefix: str) -> Path:
    path = Path("test-artifacts") / "knowledge-upload" / prefix / str(uuid.uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_file_sanitizes_name_and_snapshots_processing_params():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("sanitize")
    try:
        manager = reset_manager(str(work_dir))
        kb = await manager.create_kb(name="kb", kb_type="milvus", chunk_preset_id="qa")

        file_meta = await manager.add_file(kb.kb_id, r"folder\Guide?.txt", b"Alpha upload works.")

        assert file_meta.filename == "Guide_.txt"
        assert Path(file_meta.file_path).name.endswith("_Guide_.txt")
        assert Path(file_meta.file_path).read_bytes() == b"Alpha upload works."
        assert file_meta.processing_params["chunk_preset_id"] == "qa"
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_file_accepts_xlsx_uploads():
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("xlsx")
    try:
        manager = reset_manager(str(work_dir))
        kb = await manager.create_kb(name="kb", kb_type="milvus")

        file_meta = await manager.add_file(kb.kb_id, "医保问答.xlsx", b"excel bytes")

        assert file_meta.filename == "医保问答.xlsx"
        assert Path(file_meta.file_path).suffix == ".xlsx"
        assert Path(file_meta.file_path).read_bytes() == b"excel bytes"
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_file_rejects_bad_uploads_without_metadata(monkeypatch):
    from nexagent.knowledge.base import KnowledgeFileError
    from nexagent.knowledge.manager import reset_manager

    monkeypatch.setenv("NEXAGENT_KB_MAX_UPLOAD_BYTES", "4")
    work_dir = _work_dir("reject")
    try:
        manager = reset_manager(str(work_dir))
        kb = await manager.create_kb(name="kb", kb_type="milvus")

        for filename, content, code in [
            ("../secret.txt", b"ok", "invalid_filename"),
            ("tool.exe", b"ok", "unsupported_file_type"),
            ("empty.txt", b"", "empty_file"),
            ("large.txt", b"12345", "file_too_large"),
        ]:
            with pytest.raises(KnowledgeFileError) as exc:
                await manager.add_file(kb.kb_id, filename, content)
            assert exc.value.code == code

        assert manager.list_files(kb.kb_id) == []
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_parse_and_index_state_machine_allows_retry_and_reindex(monkeypatch):
    from nexagent.knowledge.base import KnowledgeFileError
    from nexagent.knowledge.manager import reset_manager

    monkeypatch.setenv("NEXAGENT_FORCE_LOCAL_KB_FALLBACK", "1")
    work_dir = _work_dir("state")
    try:
        manager = reset_manager(str(work_dir))
        kb = await manager.create_kb(name="kb", kb_type="milvus")
        file_meta = await manager.add_file(kb.kb_id, "guide.txt", b"Alpha retrieval works.")

        with pytest.raises(KnowledgeFileError) as exc:
            await manager.index_file(kb.kb_id, file_meta.file_id)
        assert exc.value.code == "invalid_file_state"

        parsed = await manager.parse_file(kb.kb_id, file_meta.file_id)
        assert parsed.status.value == "parsed"

        with pytest.raises(KnowledgeFileError) as exc:
            await manager.parse_file(kb.kb_id, file_meta.file_id)
        assert exc.value.code == "invalid_file_state"

        indexed = await manager.index_file(kb.kb_id, file_meta.file_id)
        assert indexed.status.value == "indexed"
        assert indexed.chunk_count >= 1

        reindexed = await manager.index_file(kb.kb_id, file_meta.file_id)
        assert reindexed.status.value == "indexed"
        assert reindexed.chunk_count == indexed.chunk_count
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_interrupted_file_statuses_recover_on_manager_load():
    from nexagent.knowledge.manager import reset_manager
    from nexagent.knowledge.models import FileStatus

    work_dir = _work_dir("recover")
    try:
        manager = reset_manager(str(work_dir))
        kb = await manager.create_kb(name="kb", kb_type="milvus")
        parsing_file = await manager.add_file(kb.kb_id, "parsing.txt", b"one")
        indexing_file = await manager.add_file(kb.kb_id, "indexing.txt", b"two")
        backend = manager._find_backend(kb.kb_id)

        async with backend._meta_lock:
            backend._files[parsing_file.file_id].status = FileStatus.PARSING
            backend._files[indexing_file.file_id].status = FileStatus.INDEXING
            backend._save_meta()

        reloaded = reset_manager(str(work_dir))

        assert reloaded.get_file(kb.kb_id, parsing_file.file_id).status == FileStatus.PARSE_ERROR
        assert reloaded.get_file(kb.kb_id, indexing_file.file_id).status == FileStatus.INDEX_ERROR
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upload_route_returns_structured_validation_error(monkeypatch):
    from nexagent.knowledge.manager import reset_manager

    work_dir = _work_dir("route")
    try:
        manager = reset_manager(str(work_dir))
        kb = await manager.create_kb(name="kb", kb_type="milvus")
        monkeypatch.setattr(knowledge, "_prod_enabled", lambda: False)
        monkeypatch.setattr(knowledge, "_kb_or_404", lambda kb_id: (manager, kb))

        upload = UploadFile(filename="../secret.txt", file=BytesIO(b"content"))

        with pytest.raises(HTTPException) as exc:
            await knowledge.upload_file(kb.kb_id, upload)

        assert exc.value.status_code == 400
        assert exc.value.detail["error_code"] == "invalid_filename"
        assert manager.list_files(kb.kb_id) == []
    finally:
        reset_manager()
        shutil.rmtree(work_dir, ignore_errors=True)
