from __future__ import annotations

import pytest


@pytest.mark.unit
def test_general_chunking_keeps_stable_chunk_ids():
    from nexagent.knowledge.chunking import chunk_markdown

    chunks = chunk_markdown(
        "Alpha beta.\n\nGamma delta.",
        file_id="file-1",
        filename="guide.md",
        processing_params={"chunk_preset_id": "general", "chunk_size": 64, "chunk_overlap": 0},
    )

    assert chunks
    assert chunks[0]["chunk_id"] == "file-1_chunk_0"
    assert chunks[0]["file_id"] == "file-1"
    assert chunks[0]["source"] == "guide.md"


@pytest.mark.unit
def test_qa_chunking_extracts_markdown_table_pairs():
    from nexagent.knowledge.chunking import chunk_markdown

    chunks = chunk_markdown(
        "| Question | Answer |\n| --- | --- |\n| What is RAG? | Retrieval augmented generation. |",
        file_id="faq",
        filename="faq.md",
        processing_params={"chunk_preset_id": "qa"},
    )

    assert len(chunks) == 1
    assert "Question: What is RAG?" in chunks[0]["content"]
    assert "Answer: Retrieval augmented generation." in chunks[0]["content"]


@pytest.mark.unit
def test_book_chunking_splits_by_markdown_headings():
    from nexagent.knowledge.chunking import chunk_markdown

    chunks = chunk_markdown(
        "# Chapter 1\nAlpha content.\n# Chapter 2\nBeta content.",
        file_id="book",
        filename="book.md",
        processing_params={"chunk_preset_id": "book", "chunk_size": 128},
    )

    assert [chunk["chunk_id"] for chunk in chunks] == ["book_chunk_0", "book_chunk_1"]
    assert "Chapter 1" in chunks[0]["content"]
    assert "Chapter 2" in chunks[1]["content"]


@pytest.mark.unit
def test_laws_chunking_splits_by_article_and_enforces_limit():
    from nexagent.knowledge.chunking import chunk_markdown

    long_body = "alpha " * 80
    chunks = chunk_markdown(
        f"Article 1 Scope\n{long_body}\nArticle 2 Duties\n{long_body}",
        file_id="law",
        filename="law.md",
        processing_params={"chunk_preset_id": "laws", "chunk_size": 120, "chunk_overlap": 0},
    )

    assert len(chunks) > 2
    assert all(len(chunk["content"]) <= 140 for chunk in chunks)


@pytest.mark.unit
def test_paper_chunking_promotes_sections_and_skips_references():
    from nexagent.knowledge.chunking import chunk_markdown

    chunks = chunk_markdown(
        "\n".join(
            [
                "A Useful Paper Title",
                "Abstract",
                "This paper studies retrieval quality.",
                "Introduction",
                "The system indexes evidence chunks.",
                "Figure 1: Retrieval pipeline.",
                "References",
                "[1] A citation that should not dominate retrieval.",
            ]
        ),
        file_id="paper",
        filename="paper.pdf",
        processing_params={"chunk_preset_id": "paper", "chunk_size": 160},
    )

    contents = "\n\n".join(chunk["content"] for chunk in chunks)
    assert chunks
    assert "## Abstract" in contents
    assert "## Introduction" in contents
    assert "Figure 1: Retrieval pipeline." in contents
    assert "References" not in contents
