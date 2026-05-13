from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
def test_document_parser_returns_parsed_document_for_text():
    from nexagent.knowledge.parser import DocumentParser

    work_dir = Path(__file__).resolve().parents[2] / ".test-artifacts" / "parser"
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "note.md"
    path.write_text("# Title\n\nBody", encoding="utf-8")

    parsed = DocumentParser().parse(path)

    assert parsed.content == "# Title\n\nBody"
    assert parsed.metadata["parser"] == "fallback"
    assert parsed.metadata["filename"] == "note.md"
    assert parsed.metadata["content_chars"] == len(parsed.content)
    assert parsed.metadata["content_sha256"]
