"""Provider-neutral, ordered document parsing for ingestion.

The parser returns exact document-derived text and locators only. It deliberately
does not perform chunking, embedding enrichment, or any model-generated rewrite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader

ElementType = Literal["heading", "paragraph", "list", "table"]

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocumentParseError(ValueError):
    """A document cannot be parsed safely into source-derived elements."""


@dataclass(frozen=True, slots=True)
class DocumentElement:
    element_type: ElementType
    text: str
    section_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    source_start: int
    source_end: int
    metadata: dict[str, object] = field(default_factory=dict)


class DocumentParser(Protocol):
    def parse(self, *, storage_path: str, mime_type: str) -> list[DocumentElement]: ...


def parse_document(
    *,
    storage_path: str,
    mime_type: str,
    provider: Literal["unstructured", "compatibility"] = "unstructured",
    allow_compatibility_fallback: bool = True,
) -> list[DocumentElement]:
    """Parse supported input while retaining a safe, local compatibility path."""
    path = Path(storage_path)
    if not path.is_file():
        raise DocumentParseError("Uploaded file is unavailable")

    if mime_type == "text/plain":
        return _parse_txt(path)
    if mime_type == DOCX_MIME:
        return _parse_docx(path)
    if mime_type == "application/pdf":
        if provider == "unstructured":
            try:
                return _parse_pdf_unstructured(path)
            except (DocumentParseError, ImportError, ModuleNotFoundError):
                if not allow_compatibility_fallback:
                    raise
        return _parse_pdf_compatibility(path)
    raise DocumentParseError(f"Unsupported document MIME type: {mime_type}")


def _element(
    *,
    element_type: ElementType,
    text: str,
    section_path: tuple[str, ...],
    page_start: int | None,
    source_start: int,
    metadata: dict[str, object] | None = None,
) -> DocumentElement:
    exact = text.strip()
    return DocumentElement(
        element_type=element_type,
        text=exact,
        section_path=section_path,
        page_start=page_start,
        page_end=page_start,
        source_start=source_start,
        source_end=source_start + len(exact),
        metadata=metadata or {},
    )


def _parse_txt(path: Path) -> list[DocumentElement]:
    source = path.read_text(encoding="utf-8", errors="ignore")
    elements: list[DocumentElement] = []
    section_path: tuple[str, ...] = ()
    offset = 0
    for block in re.split(r"\n\s*\n", source):
        exact = block.strip()
        if not exact:
            continue
        start = source.find(exact, offset)
        offset = start + len(exact)
        heading_match = re.fullmatch(r"#{1,6}\s+(.+)", exact)
        if heading_match:
            section_path = (*section_path, heading_match.group(1).strip())
            elements.append(
                _element(
                    element_type="heading",
                    text=heading_match.group(1),
                    section_path=section_path,
                    page_start=1,
                    source_start=start,
                )
            )
            continue
        element_type: ElementType = (
            "list" if re.match(r"(?:[-*]|\d+[.)])\s+", exact) else "paragraph"
        )
        elements.append(
            _element(
                element_type=element_type,
                text=exact,
                section_path=section_path,
                page_start=1,
                source_start=start,
            )
        )
    return elements


def _parse_docx(path: Path) -> list[DocumentElement]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with ZipFile(path) as archive:
        with archive.open("word/document.xml") as document_xml:
            root = ElementTree.parse(document_xml).getroot()

    body = root.find("w:body", namespace)
    if body is None:
        raise DocumentParseError("DOCX document body is missing")
    elements: list[DocumentElement] = []
    section_path: tuple[str, ...] = ()
    offset = 0
    for child in body:
        local_name = child.tag.rsplit("}", maxsplit=1)[-1]
        if local_name == "p":
            text = "".join(
                node.text or "" for node in child.findall(".//w:t", namespace)
            ).strip()
            if not text:
                continue
            style = child.find("w:pPr/w:pStyle", namespace)
            style_name = (
                style.get(f"{{{namespace['w']}}}val", "") if style is not None else ""
            ).lower()
            is_heading = style_name.startswith("heading")
            is_list = child.find("w:pPr/w:numPr", namespace) is not None
            if is_heading:
                section_path = (*section_path, text)
            element_type: ElementType = (
                "heading" if is_heading else "list" if is_list else "paragraph"
            )
            elements.append(
                _element(
                    element_type=element_type,
                    text=text,
                    section_path=section_path,
                    page_start=1,
                    source_start=offset,
                    metadata={"style": style_name} if style_name else {},
                )
            )
            offset += len(text) + 1
        elif local_name == "tbl":
            rows: list[str] = []
            for row in child.findall("w:tr", namespace):
                cells = [
                    "".join(
                        node.text or "" for node in cell.findall(".//w:t", namespace)
                    ).strip()
                    for cell in row.findall("w:tc", namespace)
                ]
                rows.append(" | ".join(cells))
            text = "\n".join(row for row in rows if row.strip()).strip()
            if text:
                elements.append(
                    _element(
                        element_type="table",
                        text=text,
                        section_path=section_path,
                        page_start=1,
                        source_start=offset,
                        metadata={"rows": len(rows), "header": rows[0] if rows else ""},
                    )
                )
                offset += len(text) + 1
    return elements


def _parse_pdf_unstructured(path: Path) -> list[DocumentElement]:
    from unstructured.partition.pdf import partition_pdf

    raw_elements = partition_pdf(
        filename=str(path), strategy="fast", chunking_strategy="by_title"
    )
    elements: list[DocumentElement] = []
    section_path: tuple[str, ...] = ()
    offset = 0
    for raw in raw_elements:
        text = str(raw).strip()
        if not text:
            continue
        category = str(getattr(raw, "category", "Text"))
        element_type: ElementType = (
            "heading"
            if category == "Title"
            else "table"
            if category == "Table"
            else "list"
            if category == "ListItem"
            else "paragraph"
        )
        if element_type == "heading":
            section_path = (*section_path, text)
        metadata = getattr(raw, "metadata", None)
        page_number = getattr(metadata, "page_number", None)
        elements.append(
            _element(
                element_type=element_type,
                text=text,
                section_path=section_path,
                page_start=page_number if isinstance(page_number, int) else None,
                source_start=offset,
            )
        )
        offset += len(text) + 1
    if not elements:
        raise DocumentParseError("PDF contains no extractable text; OCR is unsupported")
    return elements


def _parse_pdf_compatibility(path: Path) -> list[DocumentElement]:
    elements: list[DocumentElement] = []
    offset = 0
    for page_number, page in enumerate(PdfReader(str(path)).pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        elements.append(
            _element(
                element_type="paragraph",
                text=text,
                section_path=(),
                page_start=page_number,
                source_start=offset,
                metadata={"parser": "pypdf_compatibility"},
            )
        )
        offset += len(text) + 1
    if not elements:
        raise DocumentParseError("PDF contains no extractable text; OCR is unsupported")
    return elements
