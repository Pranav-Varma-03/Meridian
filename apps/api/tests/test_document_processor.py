import uuid
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.services import document_processor


def test_save_uploaded_file_persists_content(tmp_path: Path) -> None:
    document_id = uuid.uuid4()
    payload = b"hello processor"

    stored_path = document_processor.save_uploaded_file(
        document_id=document_id,
        filename="notes.txt",
        file_bytes=payload,
        storage_root=tmp_path,
    )

    saved = Path(stored_path)
    assert saved.exists()
    assert saved.read_bytes() == payload
    assert str(document_id) in saved.name


def test_extract_text_segments_for_txt(tmp_path: Path) -> None:
    txt_path = tmp_path / "sample.txt"
    txt_path.write_text("alpha beta gamma", encoding="utf-8")

    segments = document_processor.extract_text_segments(
        storage_path=str(txt_path),
        mime_type="text/plain",
    )

    assert len(segments) == 1
    assert segments[0].page_number == 1
    assert segments[0].text == "alpha beta gamma"


def test_extract_text_segments_for_docx_xml_zip(tmp_path: Path) -> None:
    docx_path = tmp_path / "sample.docx"
    xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
  <w:body>
    <w:p><w:r><w:t>First line</w:t></w:r></w:p>
    <w:p><w:r><w:t>Second line</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    with ZipFile(docx_path, "w") as archive:
        archive.writestr("word/document.xml", xml)

    segments = document_processor.extract_text_segments(
        storage_path=str(docx_path),
        mime_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )

    assert len(segments) == 1
    assert "First line" in segments[0].text
    assert "Second line" in segments[0].text


def test_build_chunks_includes_required_metadata() -> None:
    segments = [
        document_processor.TextSegment(
            page_number=2,
            text="one two three four five six seven eight nine ten",
        )
    ]

    chunks = document_processor.build_chunks(
        segments=segments,
        source_file="notes.txt",
        chunk_size=20,
        chunk_overlap=5,
    )

    assert len(chunks) >= 1
    first = chunks[0]
    assert first.chunk_index == 0
    assert first.token_count >= 1
    assert first.metadata["source_file"] == "notes.txt"
    assert first.metadata["page_number"] == 2
    assert "ingested_at" in first.metadata


@pytest.mark.asyncio
async def test_replace_document_chunks_deletes_and_adds() -> None:
    class DummySession:
        def __init__(self) -> None:
            self.executed_delete = False
            self.added: list[object] = []

        async def execute(self, _query):
            self.executed_delete = True

        def add(self, value):
            self.added.append(value)

    session = DummySession()
    document_id = uuid.uuid4()
    chunks = [
        document_processor.ChunkPayload(
            chunk_index=0,
            chunk_text="chunk text",
            token_count=2,
            metadata={"source_file": "a.txt"},
        )
    ]

    inserted = await document_processor.replace_document_chunks(
        session,  # type: ignore[arg-type]
        document_id=document_id,
        chunks=chunks,
    )

    assert session.executed_delete is True
    assert inserted == 1
    assert len(session.added) == 1
