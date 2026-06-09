from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

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


@pytest.mark.unit
def test_document_parser_extracts_xlsx_as_markdown():
    from nexagent.knowledge.parser import DocumentParser, ParseConfig

    work_dir = Path(__file__).resolve().parents[2] / ".test-artifacts" / "parser"
    work_dir.mkdir(parents=True, exist_ok=True)
    path = work_dir / "医保问答.xlsx"
    _write_minimal_xlsx(path)

    parsed = DocumentParser().parse(path, ParseConfig(prefer_docling=False))

    assert "## Sheet: 素材" in parsed.content
    assert "| 标题 | 类型 | 摘要 |" in parsed.content
    assert "| 医保电子凭证 | topic | 参保人线上凭证使用说明 |" in parsed.content
    assert parsed.metadata["parser"] == "xlsx"
    assert parsed.metadata["sheet_count"] == 1
    assert parsed.metadata["row_count"] == 2
    assert parsed.metadata["filename"] == "医保问答.xlsx"


def _write_minimal_xlsx(path: Path) -> None:
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="素材" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">
      <c r="A1" t="inlineStr"><is><t>标题</t></is></c>
      <c r="B1" t="inlineStr"><is><t>类型</t></is></c>
      <c r="C1" t="inlineStr"><is><t>摘要</t></is></c>
    </row>
    <row r="2">
      <c r="A2" t="inlineStr"><is><t>医保电子凭证</t></is></c>
      <c r="B2" t="inlineStr"><is><t>topic</t></is></c>
      <c r="C2" t="inlineStr"><is><t>参保人线上凭证使用说明</t></is></c>
    </row>
  </sheetData>
</worksheet>""",
    }
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
