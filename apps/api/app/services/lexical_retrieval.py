"""Owner-scoped PostgreSQL full-text candidate retrieval."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import DependencySpan
from app.models.entities import (
    Document,
    DocumentChunk,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    GenerationStatus,
)
from app.services.retrieval_candidates import (
    RetrievalCandidate,
    normalize_lexical_query,
)


async def retrieve_lexical_candidates(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    collection_ids: list[uuid.UUID],
    limit: int,
    timeout_ms: int = 250,
) -> list[RetrievalCandidate]:
    normalized = normalize_lexical_query(query)
    if not normalized or limit <= 0:
        return []
    with DependencySpan("postgres", "lexical_retrieval"):
        await session.execute(
            text("SET LOCAL statement_timeout = :timeout").bindparams(
                timeout=timeout_ms
            )
        )
        tsquery = func.plainto_tsquery("simple", normalized)
        rank = func.ts_rank_cd(DocumentChunk.lexical_search, tsquery)
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                DocumentIngestionGeneration.generation_number,
                rank.label("rank_score"),
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(
                DocumentIngestionGeneration,
                DocumentIngestionGeneration.id == DocumentChunk.generation_id,
            )
            .where(
                Document.user_id == user_id,
                Document.lifecycle_status == DocumentLifecycleStatus.active,
                Document.active_generation_id == DocumentIngestionGeneration.id,
                DocumentIngestionGeneration.status == GenerationStatus.active,
                DocumentChunk.lexical_search.is_not(None),
                DocumentChunk.lexical_search.op("@@")(tsquery),
            )
            .order_by(rank.desc(), DocumentChunk.id.asc())
            .limit(limit)
        )
        if collection_ids:
            statement = statement.where(Document.collection_id.in_(collection_ids))
        result = await session.execute(statement)
    return [
        RetrievalCandidate(
            chunk_id=chunk_id,
            document_id=document_id,
            generation=generation,
            channel="lexical",
            rank=index,
            score=float(score or 0.0),
        )
        for index, (chunk_id, document_id, generation, score) in enumerate(
            result.all(), start=1
        )
    ]
