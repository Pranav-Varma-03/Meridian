"""Postgres lifecycle validation for vector-store retrieval candidates.

Pinecone is a candidate index, not a lifecycle authority. This module is kept
independent of the future query/LLM service so every retrieval implementation has
one safe, testable place to reject stale vector matches.
"""

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Document,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    GenerationStatus,
)


def _metadata_for(candidate: Any) -> Mapping[str, Any] | None:
    if isinstance(candidate, Mapping):
        metadata = candidate.get("metadata", candidate)
    else:
        metadata = getattr(candidate, "metadata", None)
    return metadata if isinstance(metadata, Mapping) else None


def _candidate_identity(candidate: Any) -> tuple[uuid.UUID, int] | None:
    metadata = _metadata_for(candidate)
    if metadata is None:
        return None
    try:
        document_id = uuid.UUID(str(metadata["document_id"]))
        generation_number = int(metadata["generation"])
    except (KeyError, TypeError, ValueError):
        return None
    if generation_number < 1:
        return None
    return document_id, generation_number


async def filter_active_retrieval_candidates(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    candidates: Sequence[Any],
) -> list[Any]:
    """Return only candidates from the user's currently active generation.

    Invalid/missing metadata is intentionally excluded. A vector may remain
    query-visible during Pinecone eventual consistency, so any match that cannot
    be proven active in Postgres must never reach prompt construction.
    """
    identities = {
        identity
        for candidate in candidates
        if (identity := _candidate_identity(candidate)) is not None
    }
    if not identities:
        return []

    document_ids = [document_id for document_id, _generation in identities]
    result = await session.execute(
        select(Document.id, DocumentIngestionGeneration.generation_number)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == Document.active_generation_id,
        )
        .where(
            Document.id.in_(document_ids),
            Document.user_id == user_id,
            Document.lifecycle_status == DocumentLifecycleStatus.active,
            DocumentIngestionGeneration.status == GenerationStatus.active,
        )
    )
    active_identities = {
        (document_id, generation) for document_id, generation in result.all()
    }
    return [
        candidate
        for candidate in candidates
        if _candidate_identity(candidate) in active_identities
    ]
