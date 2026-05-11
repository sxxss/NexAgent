from __future__ import annotations

import pytest


@pytest.mark.unit
def test_file_meta_progress_is_exposed_in_dict():
    from nexagent.knowledge.models import FileMeta, FileStatus

    meta = FileMeta(
        file_id="file-a",
        kb_id="kb-a",
        filename="doc.md",
        file_path="/tmp/doc.md",
        status=FileStatus.PARSED,
        parse_metadata={"parser": "fallback", "content_chars": 128},
    )

    payload = meta.to_dict()

    assert payload["parse_metadata"]["parser"] == "fallback"
    assert payload["progress"]["percent"] == 60
    assert payload["progress"]["can_index"] is True
    assert payload["progress"]["can_process"] is False


@pytest.mark.unit
def test_search_result_payload_includes_evidence():
    from app.gateway.routers.knowledge import _search_result_payload

    class Result:
        content = "hello world"
        score = 0.91
        source = "doc.md"
        file_id = "file-a"
        metadata = {"source": "doc.md"}

        def evidence(self, index: int) -> dict:
            return {"id": f"E{index}", "source": self.source, "score": self.score, "metadata": self.metadata}

        def to_dict(self) -> dict:
            return {
                "content": self.content,
                "score": self.score,
                "source": self.source,
                "file_id": self.file_id,
                "metadata": self.metadata,
            }

    payload = _search_result_payload(Result(), 2)

    assert payload["evidence"]["id"] == "E2"
    assert payload["source"] == "doc.md"
