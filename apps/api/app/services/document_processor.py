import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import DocumentChunk

DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 64


@dataclass(slots=True)
class TextSegment:
    page_number: int | None
    text: str


@dataclass(slots=True)
class ChunkPayload:
    chunk_index: int
    chunk_text: str
    token_count: int
    metadata: dict


def _default_storage_root() -> Path:
    # <repo>/Meridian/apps/api/app/services/document_processor.py -> <repo>/Meridian/data/uploads
    return Path(__file__).resolve().parents[4] / "data" / "uploads"


def sanitize_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", filename.strip())
    return cleaned or "uploaded-file"


def save_uploaded_file(
    *,
    document_id: uuid.UUID,
    filename: str,
    file_bytes: bytes,
    storage_root: Path | None = None,
) -> str:
    root = storage_root or _default_storage_root()
    root.mkdir(parents=True, exist_ok=True)

    safe_name = sanitize_filename(filename)
    destination = root / f"{document_id}_{safe_name}"
    destination.write_bytes(file_bytes)
    return str(destination)


def _parse_txt(path: Path) -> list[TextSegment]:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []
    return [TextSegment(page_number=1, text=text)]


def _parse_pdf(path: Path) -> list[TextSegment]:
    reader = PdfReader(str(path))
    segments: list[TextSegment] = []
    for index, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append(TextSegment(page_number=index, text=text))
    return segments


def _parse_docx(path: Path) -> list[TextSegment]:
    paragraphs: list[str] = []
    with ZipFile(path) as archive:
        with archive.open("word/document.xml") as document_xml:
            tree = ElementTree.parse(document_xml)

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for paragraph in tree.findall(".//w:p", namespace):
        runs = paragraph.findall(".//w:t", namespace)
        text = "".join(run.text or "" for run in runs).strip()
        if text:
            paragraphs.append(text)

    text = "\n".join(paragraphs).strip()
    if not text:
        return []
    return [TextSegment(page_number=1, text=text)]


def extract_text_segments(*, storage_path: str, mime_type: str) -> list[TextSegment]:
    path = Path(storage_path)
    if not path.exists() or not path.is_file():
        return []

    if mime_type == "text/plain":
        return _parse_txt(path)
    if mime_type == "application/pdf":
        return _parse_pdf(path)
    if (
        mime_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return _parse_docx(path)
    return []


def _split_with_overlap(text: str, chunk_size: int, overlap: int) -> list[str]:
    if chunk_size <= 0:
        return []
    if overlap >= chunk_size:
        overlap = max(0, chunk_size - 1)

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks


def build_chunks(
    *,
    segments: list[TextSegment],
    source_file: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[ChunkPayload]:
    payloads: list[ChunkPayload] = []
    chunk_index = 0
    for segment in segments:
        segment_chunks = _split_with_overlap(
            segment.text,
            chunk_size=chunk_size,
            overlap=chunk_overlap,
        )
        for chunk_text in segment_chunks:
            token_count = max(1, len(chunk_text.split()))
            payloads.append(
                ChunkPayload(
                    chunk_index=chunk_index,
                    chunk_text=chunk_text,
                    token_count=token_count,
                    metadata={
                        "source_file": source_file,
                        "page_number": segment.page_number,
                        "chunk_index": chunk_index,
                        "section_heading": None,
                        "ingested_at": datetime.now(UTC).isoformat(),
                    },
                )
            )
            chunk_index += 1
    return payloads


async def replace_document_chunks(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    chunks: list[ChunkPayload],
) -> int:
    await session.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )

    for chunk in chunks:
        session.add(
            DocumentChunk(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                token_count=chunk.token_count,
                chunk_text=chunk.chunk_text,
                vector_id=None,
                metadata_json=chunk.metadata,
            )
        )
    return len(chunks)
