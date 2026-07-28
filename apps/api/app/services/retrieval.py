"""Owner-scoped, lifecycle-safe vector retrieval for grounded chat."""

import asyncio
import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from pinecone import Pinecone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.entities import (
    Collection,
    Document,
    DocumentChunk,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    GenerationStatus,
)
from app.services import embeddings
from app.services.retrieval_lifecycle import filter_active_retrieval_candidates


class CollectionAccessError(Exception):
    """Raised when a requested collection is not owned by the current user."""


class RetrievalUnavailableError(Exception):
    """Raised when an embedding or vector dependency cannot serve a request."""


@dataclass(frozen=True, slots=True)
class RetrievedSource:
    document_id: uuid.UUID
    generation: int
    chunk_id: str
    filename: str
    chunk_text: str
    score: float
    page_number: int | None
    section_heading: str | None

    def citation(self) -> dict[str, Any]:
        excerpt = self.chunk_text[:1000]
        return {
            "document_id": str(self.document_id),
            "generation": self.generation,
            "chunk_id": self.chunk_id,
            "filename": self.filename,
            "page_number": self.page_number,
            "section_heading": self.section_heading,
            "excerpt": excerpt,
            "content_sha256": hashlib.sha256(
                self.chunk_text.encode("utf-8")
            ).hexdigest(),
            "score": self.score,
        }


def _metadata(candidate: Any) -> Mapping[str, Any] | None:
    value = (
        candidate.get("metadata")
        if isinstance(candidate, Mapping)
        else getattr(candidate, "metadata", None)
    )
    return value if isinstance(value, Mapping) else None


def _score(candidate: Any) -> float:
    value = (
        candidate.get("score", 0)
        if isinstance(candidate, Mapping)
        else getattr(candidate, "score", 0)
    )
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _candidate_identity(candidate: Any) -> tuple[uuid.UUID, int, uuid.UUID] | None:
    metadata = _metadata(candidate)
    if metadata is None:
        return None
    try:
        document_id = uuid.UUID(str(metadata["document_id"]))
        generation = int(metadata["generation"])
        chunk_id = uuid.UUID(str(metadata["chunk_id"]))
    except (KeyError, TypeError, ValueError):
        return None
    if generation < 1:
        return None
    return document_id, generation, chunk_id


def _page_number(metadata: Mapping[str, Any]) -> int | None:
    page_value = metadata.get("page_number")
    try:
        return int(page_value) if page_value not in (None, "") else None
    except (TypeError, ValueError):
        return None


async def _hydrate_active_chunks(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    candidates: list[Any],
) -> list[RetrievedSource]:
    """Load candidate text from Postgres, never from Pinecone metadata.

    Pinecone is a similarity index and can omit fields because of old vector records,
    metadata-size limits, or indexing configuration. Postgres owns the immutable chunk
    text and provides a second document/generation lifecycle fence before content is
    included in a model prompt.
    """
    parsed = [
        (candidate, identity)
        for candidate in candidates
        if (identity := _candidate_identity(candidate)) is not None
    ]
    if not parsed:
        return []

    chunk_ids = [
        chunk_id for _candidate, (_document_id, _generation, chunk_id) in parsed
    ]
    result = await session.execute(
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentIngestionGeneration.generation_number,
            DocumentChunk.chunk_text,
            Document.filename,
            DocumentChunk.metadata_json,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == DocumentChunk.generation_id,
        )
        .where(
            DocumentChunk.id.in_(chunk_ids),
            Document.user_id == user_id,
            Document.lifecycle_status == DocumentLifecycleStatus.active,
            Document.active_generation_id == DocumentIngestionGeneration.id,
            DocumentIngestionGeneration.status == GenerationStatus.active,
        )
    )
    chunks = {
        chunk_id: (document_id, generation, chunk_text, filename, metadata or {})
        for chunk_id, document_id, generation, chunk_text, filename, metadata in result.all()
    }

    sources: list[RetrievedSource] = []
    for candidate, (document_id, generation, chunk_id) in parsed:
        chunk = chunks.get(chunk_id)
        if chunk is None:
            continue
        (
            persisted_document_id,
            persisted_generation,
            chunk_text,
            filename,
            chunk_metadata,
        ) = chunk
        # Defend against a malformed or stale vector that names a different chunk,
        # document, or generation than the authoritative row.
        if (
            persisted_document_id != document_id
            or persisted_generation != generation
            or not chunk_text.strip()
        ):
            continue
        heading = chunk_metadata.get("section_heading")
        sources.append(
            RetrievedSource(
                document_id=document_id,
                generation=generation,
                chunk_id=str(chunk_id),
                filename=filename,
                chunk_text=chunk_text.strip(),
                score=_score(candidate),
                page_number=_page_number(chunk_metadata),
                section_heading=str(heading) if heading else None,
            )
        )
    return sources


async def _validate_collection_ids(
    session: AsyncSession, *, user_id: uuid.UUID, collection_ids: list[uuid.UUID]
) -> None:
    if not collection_ids:
        return
    result = await session.scalars(
        select(Collection.id).where(
            Collection.user_id == user_id, Collection.id.in_(collection_ids)
        )
    )
    if set(result.all()) != set(collection_ids):
        raise CollectionAccessError("Collection not found")


async def retrieve_sources(
    session: AsyncSession,
    *,
    settings: Settings,
    pinecone_client: Pinecone,
    query: str,
    user_id: uuid.UUID,
    collection_ids: list[uuid.UUID] | None = None,
    openai_client: AsyncOpenAI | None = None,
) -> list[RetrievedSource]:
    """Query one owner namespace then prove each returned match is live in Postgres."""
    selected_collections = collection_ids or []
    await _validate_collection_ids(
        session, user_id=user_id, collection_ids=selected_collections
    )
    try:
        vector = await embeddings.embed_query(
            provider=settings.embedding_provider,
            model=settings.embedding_model,
            query=query,
            pinecone_client=pinecone_client,
            openai_client=openai_client,
        )
        metadata_filter: dict[str, Any] | None = None
        if selected_collections:
            metadata_filter = {
                "collection_id": {"$in": [str(value) for value in selected_collections]}
            }
        index = pinecone_client.Index(settings.pinecone_index_name)
        response = await asyncio.to_thread(
            index.query,
            vector=vector,
            top_k=settings.chat_retrieval_top_k * settings.chat_retrieval_overfetch,
            namespace=embeddings.build_pinecone_namespace(user_id=user_id),
            include_metadata=True,
            filter=metadata_filter,
        )
    except ValueError:
        raise
    except Exception as exc:
        raise RetrievalUnavailableError("Retrieval is temporarily unavailable") from exc

    candidates = getattr(response, "matches", None)
    if candidates is None and isinstance(response, Mapping):
        candidates = response.get("matches", [])
    active = await filter_active_retrieval_candidates(
        session, user_id=user_id, candidates=list(candidates or [])
    )
    normalized = await _hydrate_active_chunks(
        session,
        user_id=user_id,
        candidates=active,
    )
    qualifying = [
        source
        for source in normalized
        if source.score >= settings.chat_retrieval_score_threshold
    ]
    qualifying.sort(key=lambda source: source.score, reverse=True)
    return qualifying[: settings.chat_retrieval_max_sources]
