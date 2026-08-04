from pathlib import Path
from zipfile import ZipFile

import pytest

from app.services.document_parsing import DOCX_MIME, DocumentParseError, parse_document


def test_txt_parser_preserves_order_offsets_and_markdown_heading(
    tmp_path: Path,
) -> None:
    path = tmp_path / "guide.txt"
    path.write_text(
        "# Travel\n\n- Keep receipts\n\nMeals are reimbursable.", encoding="utf-8"
    )

    elements = parse_document(storage_path=str(path), mime_type="text/plain")

    assert [element.element_type for element in elements] == [
        "heading",
        "list",
        "paragraph",
    ]
    assert elements[1].section_path == ("Travel",)
    assert elements[1].source_start < elements[2].source_start
    assert all(element.source_end > element.source_start for element in elements)


def test_docx_parser_retains_heading_list_and_table(tmp_path: Path) -> None:
    path = tmp_path / "guide.docx"
    xml = """<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body>
<w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr><w:r><w:t>Travel</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>Keep receipts</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Limit</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>"""
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)

    elements = parse_document(storage_path=str(path), mime_type=DOCX_MIME)

    assert [element.element_type for element in elements] == [
        "heading",
        "list",
        "table",
    ]
    assert elements[1].section_path == ("Travel",)
    assert elements[2].metadata["rows"] == 1


def test_parser_rejects_unsupported_or_empty_scanned_like_document(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unsupported.bin"
    path.write_bytes(b"not a document")

    with pytest.raises(DocumentParseError, match="Unsupported"):
        parse_document(storage_path=str(path), mime_type="application/octet-stream")
