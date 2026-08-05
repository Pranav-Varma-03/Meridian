"""Persistence helpers for versioned structured ingestion generations."""

from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import DocumentChunk, DocumentParentWindow
from app.services.structured_chunking import ParentWindow, StructuredChild


async def persist_parent_child_generation(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    generation_id: uuid.UUID,
    source_file: str,
    strategy_version: str,
    children: list[StructuredChild],
    parents: list[ParentWindow],
) -> list[DocumentChunk]:
    """Persist a complete pending generation without changing legacy chunks.

    Parent windows are deliberately stored separately from `document_chunks`, so
    document child counts and vector manifests continue to describe children only.
    """
    parent_rows = [
        DocumentParentWindow(
            document_id=document_id,
            generation_id=generation_id,
            parent_index=parent.parent_index,
            source_text=parent.source_text,
            token_count=parent.token_count,
            section_path=list(parent.section_path),
            page_start=parent.page_start,
            page_end=parent.page_end,
            source_start=parent.source_start,
            source_end=parent.source_end,
        )
        for parent in parents
    ]
    session.add_all(parent_rows)
    await session.flush()
    parent_ids = {row.parent_index: row.id for row in parent_rows}

    rows: list[DocumentChunk] = []
    for child in children:
        metadata = {
            "source_file": source_file,
            "chunk_index": child.child_index,
            "page_number": child.page_start,
            "section_heading": child.section_path[-1] if child.section_path else None,
        }
        row = DocumentChunk(
            document_id=document_id,
            generation_id=generation_id,
            parent_id=parent_ids.get(child.parent_index),
            chunk_index=child.child_index,
            token_count=child.token_count,
            # This is the canonical Postgres evidence text. No generated context
            # may be assigned here.
            chunk_text=child.source_text,
            embedding_text=child.embedding_text,
            section_path=list(child.section_path),
            page_start=child.page_start,
            page_end=child.page_end,
            source_start=child.source_start,
            source_end=child.source_end,
            strategy_version=strategy_version,
            lexical_search=func.to_tsvector("simple", child.embedding_text),
            vector_id=None,
            metadata_json=metadata,
        )
        rows.append(row)
    session.add_all(rows)
    await session.flush()

    for index, row in enumerate(rows):
        row.previous_chunk_id = rows[index - 1].id if index else None
        row.next_chunk_id = rows[index + 1].id if index + 1 < len(rows) else None
    await session.flush()
    return rows


def uses_structured_generation(configuration: object) -> bool:
    """Keep generations created before the versioned configuration compatible."""
    if not isinstance(configuration, dict):
        return False
    chunker = configuration.get("chunker")
    return isinstance(chunker, dict) and chunker.get("strategy") == (
        "structure_aware_parent_child_v1"
    )
