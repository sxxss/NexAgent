"""Preset-based text chunking for NexAgent knowledge indexing."""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CHUNK_PRESET_GENERAL = "general"
CHUNK_PRESET_QA = "qa"
CHUNK_PRESET_BOOK = "book"
CHUNK_PRESET_LAWS = "laws"
CHUNK_PRESET_PAPER = "paper"
CHUNK_PRESET_IDS = {
    CHUNK_PRESET_GENERAL,
    CHUNK_PRESET_QA,
    CHUNK_PRESET_BOOK,
    CHUNK_PRESET_LAWS,
    CHUNK_PRESET_PAPER,
}
CHUNK_ENGINE_VERSION = "ragflow_like_v1"


@dataclass
class Chunk:
    """A single text chunk ready for embedding."""

    content: str
    chunk_index: int
    metadata: dict = field(default_factory=dict)
    chunk_id: str = ""
    source: str = ""


def split_text(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    separators: list[str] | None = None,
    *,
    chunk_preset_id: str | None = None,
    chunk_parser_config: dict[str, Any] | None = None,
    file_id: str = "",
    filename: str = "",
) -> list[Chunk]:
    """Split text into chunks while preserving the legacy call signature."""

    params = resolve_chunk_processing_params(
        {
            "chunk_preset_id": chunk_preset_id or CHUNK_PRESET_GENERAL,
            "chunk_parser_config": chunk_parser_config or {},
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "separators": separators or [],
        }
    )
    records = chunk_markdown(text, file_id=file_id, filename=filename, processing_params=params)
    return [
        Chunk(
            content=record["content"],
            chunk_index=int(record["chunk_index"]),
            chunk_id=str(record["chunk_id"]),
            source=str(record.get("source") or filename or ""),
            metadata={
                "chunk_id": record["chunk_id"],
                "source": record.get("source") or filename or "",
                "file_id": file_id,
                "filename": filename,
                "chunk_preset_id": params["chunk_preset_id"],
                "chunk_engine_version": CHUNK_ENGINE_VERSION,
            },
        )
        for record in records
    ]


def chunk_markdown(
    markdown_content: str,
    file_id: str,
    filename: str,
    processing_params: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return stable chunk records for parsed markdown/plain text."""

    params = resolve_chunk_processing_params(processing_params)
    preset_id = params["chunk_preset_id"]
    config = dict(params.get("chunk_parser_config") or {})
    text = markdown_content or ""
    if not text.strip():
        return []

    if preset_id == CHUNK_PRESET_QA:
        chunks = _split_qa(filename, text, config)
    elif preset_id == CHUNK_PRESET_BOOK:
        chunks = _split_book(text, config)
    elif preset_id == CHUNK_PRESET_LAWS:
        chunks = _split_laws(text, config)
    elif preset_id == CHUNK_PRESET_PAPER:
        chunks = _split_paper(text, config)
    else:
        chunks = _split_general(text, config)

    if not chunks:
        chunks = _simple_split_text(text, _chunk_size(config), _chunk_overlap(config))

    return _build_chunk_records(chunks, file_id=file_id, filename=filename, preset_id=preset_id)


def resolve_chunk_processing_params(
    kb_params: dict[str, Any] | None = None,
    file_params: dict[str, Any] | None = None,
    request_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge KB/file/request chunking params into one deterministic snapshot."""

    kb = dict(kb_params or {})
    file_specific = dict(file_params or {})
    request = dict(request_params or {})
    preset_id = normalize_chunk_preset_id(
        request.get("chunk_preset_id") or file_specific.get("chunk_preset_id") or kb.get("chunk_preset_id")
    )
    parser_config = get_default_chunk_parser_config(preset_id)
    for source in (kb, file_specific, request):
        if isinstance(source.get("chunk_parser_config"), dict):
            parser_config = _deep_merge(parser_config, source["chunk_parser_config"])
    parser_config = _deep_merge(parser_config, _legacy_params_to_parser_config(kb))
    parser_config = _deep_merge(parser_config, _legacy_params_to_parser_config(file_specific))
    parser_config = _deep_merge(parser_config, _legacy_params_to_parser_config(request))

    snapshot: dict[str, Any] = {}
    snapshot.update(file_specific)
    snapshot.update(request)
    snapshot["chunk_preset_id"] = preset_id
    snapshot["chunk_parser_config"] = parser_config
    snapshot["chunk_engine_version"] = CHUNK_ENGINE_VERSION
    snapshot["chunk_size"] = _chunk_size(parser_config)
    snapshot["chunk_overlap"] = _chunk_overlap(parser_config)
    if "qa_separator" not in snapshot and isinstance(parser_config.get("delimiter"), str):
        snapshot["qa_separator"] = parser_config["delimiter"]
    return snapshot


def normalize_chunk_preset_id(value: Any) -> str:
    normalized = str(value or CHUNK_PRESET_GENERAL).strip().lower()
    if normalized == "naive":
        normalized = CHUNK_PRESET_GENERAL
    if normalized not in CHUNK_PRESET_IDS:
        logger.warning("Unknown chunk preset %r; falling back to general", value)
        return CHUNK_PRESET_GENERAL
    return normalized


def get_default_chunk_parser_config(preset_id: str) -> dict[str, Any]:
    preset = normalize_chunk_preset_id(preset_id)
    defaults: dict[str, Any] = {
        "chunk_token_num": 512,
        "overlapped_percent": 12,
        "delimiter": "\n",
    }
    if preset in {CHUNK_PRESET_QA, CHUNK_PRESET_BOOK, CHUNK_PRESET_LAWS, CHUNK_PRESET_PAPER}:
        defaults["overlapped_percent"] = 0
    if preset == CHUNK_PRESET_PAPER:
        defaults["chunk_token_num"] = 768
        defaults["keep_references"] = False
    return defaults


def get_chunk_preset_options() -> list[dict[str, str]]:
    return [
        {"value": CHUNK_PRESET_GENERAL, "label": "General", "description": "General paragraph/text chunking."},
        {"value": CHUNK_PRESET_QA, "label": "QA", "description": "Question-answer pair chunking."},
        {"value": CHUNK_PRESET_BOOK, "label": "Book", "description": "Heading-aware long document chunking."},
        {"value": CHUNK_PRESET_LAWS, "label": "Laws", "description": "Article and clause-aware legal text chunking."},
        {"value": CHUNK_PRESET_PAPER, "label": "Paper", "description": "Paper section, abstract, table and figure-aware chunking."},
    ]


def _split_general(text: str, config: dict[str, Any]) -> list[str]:
    chunk_size = _chunk_size(config)
    chunk_overlap = _chunk_overlap(config)
    separators = config.get("separators")
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=separators
            if isinstance(separators, list) and separators
            else ["\n\n", "\n", "\u3002", "\uff1b", "\uff0c", ".", "!", "?", " ", ""],
            length_function=len,
        )
        return [doc.page_content.strip() for doc in splitter.create_documents([text]) if doc.page_content.strip()]
    except ImportError:
        logger.debug("langchain_text_splitters not available; using built-in simple chunking")
        return _simple_split_text(text, chunk_size, chunk_overlap)


def _split_qa(filename: str, text: str, config: dict[str, Any]) -> list[str]:
    pairs: list[tuple[str, str]] = []
    pairs.extend(_extract_markdown_table_pairs(text))
    pairs.extend(_extract_prefix_pairs(text))
    if not pairs and filename.lower().endswith((".csv", ".tsv", ".txt")):
        pairs.extend(_extract_delimited_pairs(text))
    pairs = _dedupe_pairs(pairs)
    if pairs:
        return [f"Question: {_clean(q)}\nAnswer: {_clean(a)}" for q, a in pairs if _clean(q) and _clean(a)]
    return _split_general(text, config)


def _split_book(text: str, config: dict[str, Any]) -> list[str]:
    sections = _sections_by_markdown_heading(text)
    if len(sections) <= 1:
        return _split_general(text, config)
    return _enforce_chunk_size(sections, config)


def _split_laws(text: str, config: dict[str, Any]) -> list[str]:
    lines = [_strip_markdown(line) for line in text.splitlines() if _strip_markdown(line)]
    if not lines:
        return []

    sections: list[str] = []
    current: list[str] = []
    article_pattern = re.compile(
        r"^(第[零一二三四五六七八九十百千万0-9]+条|第[0-9]+条|Article\s+[0-9IVXLCDM]+|Section\s+[0-9.]+)\b",
        flags=re.IGNORECASE,
    )
    for line in lines:
        if current and article_pattern.match(line):
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))
    if len(sections) <= 1:
        sections = _sections_by_markdown_heading(text)
    return _enforce_chunk_size(sections, config)


def _split_paper(text: str, config: dict[str, Any]) -> list[str]:
    """Split academic papers by structural sections before size enforcement."""
    normalized = _normalize_paper_headings(text)
    sections = _sections_by_markdown_heading(normalized)
    if len(sections) <= 1:
        sections = _sections_by_paper_markers(normalized)
    if not config.get("keep_references", False):
        sections = [
            section
            for section in sections
            if not re.match(r"^#{1,6}\s*(references|bibliography|参考文献)\b", section.strip(), re.IGNORECASE)
        ]
    enriched: list[str] = []
    caption_buffer: list[str] = []
    caption_re = re.compile(r"^(figure|fig\.|table|图|表)\s*[\w一二三四五六七八九十0-9.-]*[:：.]\s*", re.IGNORECASE)
    for section in sections:
        lines = [line.rstrip() for line in section.splitlines()]
        kept: list[str] = []
        for line in lines:
            if caption_re.match(line.strip()):
                caption_buffer.append(line.strip())
                kept.append(line)
            else:
                kept.append(line)
        content = "\n".join(kept).strip()
        if content:
            enriched.append(content)
    if caption_buffer:
        enriched.append("## Figures and Tables\n" + "\n".join(caption_buffer))
    return _enforce_chunk_size(enriched or sections, config)


def _normalize_paper_headings(text: str) -> str:
    """Promote common PDF-extracted paper section lines to markdown headings."""
    section_re = re.compile(
        r"^\s*(?:\d+(?:\.\d+)*\s+)?"
        r"(abstract|introduction|related work|background|method|methodology|approach|"
        r"experiment(?:s)?|evaluation|result(?:s)?|discussion|conclusion|"
        r"acknowledg(?:e)?ments?|references|bibliography|摘要|引言|相关工作|方法|实验|结果|讨论|结论|参考文献)"
        r"\s*$",
        re.IGNORECASE,
    )
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("#"):
            out.append(line)
        elif section_re.match(line):
            out.append(f"## {line.strip()}")
        else:
            out.append(line)
    return "\n".join(out)


def _sections_by_paper_markers(text: str) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    marker_re = re.compile(
        r"^\s*(?:\d+(?:\.\d+)*\s+)?"
        r"(Abstract|Introduction|Related Work|Background|Method|Methodology|Approach|"
        r"Experiments?|Evaluation|Results?|Discussion|Conclusion|References|Bibliography|"
        r"摘要|引言|相关工作|方法|实验|结果|讨论|结论|参考文献)\b",
        re.IGNORECASE,
    )
    for raw in text.splitlines():
        line = raw.rstrip()
        if current and marker_re.match(line):
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [section for section in sections if section]


def _build_chunk_records(
    chunks: list[str],
    *,
    file_id: str,
    filename: str,
    preset_id: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, raw in enumerate(chunks):
        content = _clean(raw)
        if not content:
            continue
        stable_id = f"{file_id}_chunk_{len(records)}" if file_id else f"chunk_{len(records)}"
        records.append(
            {
                "id": stable_id,
                "chunk_id": stable_id,
                "content": content,
                "file_id": file_id,
                "filename": filename,
                "source": filename,
                "chunk_index": len(records),
                "metadata": {
                    "chunk_id": stable_id,
                    "chunk_preset_id": preset_id,
                    "chunk_engine_version": CHUNK_ENGINE_VERSION,
                },
            }
        )
    return records


def _simple_split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - chunk_overlap)
    while start < len(text):
        end = min(start + chunk_size, len(text))
        content = text[start:end].strip()
        if content:
            chunks.append(content)
        start += step
    return chunks


def _sections_by_markdown_heading(text: str) -> list[str]:
    sections: list[str] = []
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if current and re.match(r"^#{1,6}\s+\S+", line):
            sections.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current).strip())
    return [section for section in sections if section]


def _enforce_chunk_size(chunks: list[str], config: dict[str, Any]) -> list[str]:
    limit = _chunk_size(config)
    overlap = _chunk_overlap(config)
    out: list[str] = []
    for chunk in chunks:
        if len(chunk) <= limit:
            out.append(chunk)
        else:
            out.extend(_split_general(chunk, {**config, "chunk_token_num": limit, "overlapped_percent": 0}))
    return out or _simple_split_text("\n\n".join(chunks), limit, overlap)


def _extract_markdown_table_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if "|" not in stripped:
            continue
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        cells = [cell.strip() for cell in stripped.split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells if cell):
            continue
        if cells[0].lower() in {"q", "question", "问题"} and cells[1].lower() in {"a", "answer", "答案", "回答"}:
            continue
        if cells[0] and cells[1]:
            pairs.append((cells[0], cells[1]))
    return pairs


def _extract_prefix_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    question = ""
    answer_lines: list[str] = []
    q_pattern = re.compile(r"^(Q|Question|问题|问)\s*[:：]\s*(.*)$", re.IGNORECASE)
    a_pattern = re.compile(r"^(A|Answer|答案|回答)\s*[:：]\s*(.*)$", re.IGNORECASE)
    for line in text.splitlines():
        q_match = q_pattern.match(line.strip())
        if q_match:
            if question and answer_lines:
                pairs.append((question, "\n".join(answer_lines)))
            question = q_match.group(2).strip()
            answer_lines = []
            continue
        a_match = a_pattern.match(line.strip())
        if a_match:
            answer_lines.append(a_match.group(2).strip())
            continue
        if question:
            answer_lines.append(line)
    if question and answer_lines:
        pairs.append((question, "\n".join(answer_lines)))
    return pairs


def _extract_delimited_pairs(text: str) -> list[tuple[str, str]]:
    delimiter = "\t" if any("\t" in line for line in text.splitlines()) else ","
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(delimiter, 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            pairs.append((parts[0], parts[1]))
    return pairs


def _dedupe_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for q, a in pairs:
        key = (_clean(q), _clean(a))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _legacy_params_to_parser_config(params: dict[str, Any]) -> dict[str, Any]:
    parser_config: dict[str, Any] = {}
    chunk_size = _safe_int(params.get("chunk_size"))
    chunk_overlap = _safe_int(params.get("chunk_overlap"))
    if chunk_size and chunk_size > 0:
        parser_config["chunk_token_num"] = chunk_size
    if chunk_size and chunk_size > 0 and chunk_overlap is not None:
        overlap_percent = round(max(0, min(chunk_overlap, chunk_size - 1)) * 100 / chunk_size)
        parser_config["overlapped_percent"] = max(0, min(overlap_percent, 99))
    for key in ("delimiter", "qa_separator"):
        if isinstance(params.get(key), str) and params[key]:
            parser_config["delimiter"] = _unescape_delimiter(params[key])
    if "chunk_token_num" in params:
        token_num = _safe_int(params.get("chunk_token_num"))
        if token_num is not None:
            parser_config["chunk_token_num"] = token_num
    if "overlapped_percent" in params:
        overlap = _safe_int(params.get("overlapped_percent"))
        if overlap is not None:
            parser_config["overlapped_percent"] = max(0, min(overlap, 99))
    if isinstance(params.get("separators"), list):
        parser_config["separators"] = params["separators"]
    return parser_config


def _chunk_size(config: dict[str, Any]) -> int:
    return max(64, min(_safe_int(config.get("chunk_token_num")) or 512, 65535))


def _chunk_overlap(config: dict[str, Any]) -> int:
    size = _chunk_size(config)
    overlap_percent = max(0, min(_safe_int(config.get("overlapped_percent")) or 0, 99))
    return min(size - 1, int(size * overlap_percent / 100))


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _unescape_delimiter(delimiter: str) -> str:
    return delimiter.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t").replace("\\\\", "\\")


def _strip_markdown(line: str) -> str:
    text = (line or "").strip()
    text = re.sub(r"^#{1,6}\s+", "", text)
    text = re.sub(r"^[-*+]\s+", "", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())
