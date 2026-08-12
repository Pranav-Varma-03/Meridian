"""Owner-scoped, lifecycle-safe vector retrieval for grounded chat."""

import asyncio
import hashlib
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI
from pinecone import Pinecone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.observability import (
    DependencySpan,
    record_rag_stage_observation,
    record_retrieval_observation,
    retrieval_event,
)
from app.models.entities import (
    Collection,
    Document,
    DocumentChunk,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    DocumentParentWindow,
    GenerationStatus,
)
from app.services import embeddings
from app.services.lexical_retrieval import retrieve_lexical_candidates
from app.services.reranking import Reranker, apply_reranker
from app.services.retrieval_candidates import (
    FusedCandidate,
    RetrievalCandidate,
    fuse_ranked_candidates,
)


class CollectionAccessError(Exception):
    """Raised when a requested collection is not owned by the current user."""


class RetrievalUnavailableError(Exception):
    """Raised when an embedding or vector dependency cannot serve a request."""


logger = logging.getLogger(__name__)


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
    parent_id: str | None = None
    supporting_chunk_ids: tuple[str, ...] = ()
    section_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None

    def citation(self) -> dict[str, Any]:
        excerpt = self.chunk_text[:1000]
        citation = {
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
        if self.parent_id:
            citation["parent_id"] = self.parent_id
        if self.supporting_chunk_ids:
            citation["supporting_chunk_ids"] = list(self.supporting_chunk_ids)
        if self.section_path:
            citation["section_path"] = list(self.section_path)
        if self.page_start is not None:
            citation["page_start"] = self.page_start
        if self.page_end is not None:
            citation["page_end"] = self.page_end
        return citation


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


def _dense_candidates(matches: list[Any]) -> list[RetrievalCandidate]:
    candidates: list[RetrievalCandidate] = []
    for rank, match in enumerate(matches, start=1):
        identity = _candidate_identity(match)
        if identity is None:
            continue
        document_id, generation, chunk_id = identity
        candidates.append(
            RetrievalCandidate(
                chunk_id=chunk_id,
                document_id=document_id,
                generation=generation,
                channel="dense",
                rank=rank,
                score=_score(match),
            )
        )
    return candidates


async def _hydrate_active_chunks(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    candidates: list[RetrievalCandidate] | list[FusedCandidate],
) -> list[RetrievedSource]:
    """Load candidate text from Postgres, never from Pinecone metadata.

    Pinecone is a similarity index and can omit fields because of old vector records,
    metadata-size limits, or indexing configuration. Postgres owns the immutable chunk
    text and provides a second document/generation lifecycle fence before content is
    included in a model prompt.
    """
    if not candidates:
        return []

    chunk_ids = [candidate.chunk_id for candidate in candidates]
    with DependencySpan("postgres", "lifecycle_hydration"):
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
    for candidate in candidates:
        document_id = candidate.document_id
        generation = candidate.generation
        chunk_id = candidate.chunk_id
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
                score=candidate.score,
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


async def _expand_lifecycle_valid_sources(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    sources: list[RetrievedSource],
    collection_ids: list[uuid.UUID],
) -> list[RetrievedSource]:
    """Promote children to exact parents or bounded same-generation neighbors."""
    if not sources:
        return []
    source_ids = [uuid.UUID(source.chunk_id) for source in sources]
    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentIngestionGeneration.generation_number,
            DocumentChunk.chunk_text,
            Document.filename,
            DocumentChunk.metadata_json,
            DocumentChunk.parent_id,
            DocumentChunk.previous_chunk_id,
            DocumentChunk.next_chunk_id,
            DocumentParentWindow.source_text,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == DocumentChunk.generation_id,
        )
        .outerjoin(
            DocumentParentWindow, DocumentParentWindow.id == DocumentChunk.parent_id
        )
        .where(
            DocumentChunk.id.in_(source_ids),
            Document.user_id == user_id,
            Document.lifecycle_status == DocumentLifecycleStatus.active,
            Document.active_generation_id == DocumentIngestionGeneration.id,
            DocumentIngestionGeneration.status == GenerationStatus.active,
        )
    )
    if collection_ids:
        statement = statement.where(Document.collection_id.in_(collection_ids))
    result = await session.execute(statement)
    rows = {row[0]: row for row in result.all()}
    neighbor_ids = {
        neighbor_id
        for row in rows.values()
        if row[6] is None
        for neighbor_id in (row[7], row[8])
        if neighbor_id is not None
    }
    neighbors: dict[uuid.UUID, str] = {}
    if neighbor_ids:
        neighbor_statement = (
            select(DocumentChunk.id, DocumentChunk.chunk_text)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(
                DocumentIngestionGeneration,
                DocumentIngestionGeneration.id == DocumentChunk.generation_id,
            )
            .where(
                DocumentChunk.id.in_(neighbor_ids),
                Document.user_id == user_id,
                Document.lifecycle_status == DocumentLifecycleStatus.active,
                Document.active_generation_id == DocumentIngestionGeneration.id,
                DocumentIngestionGeneration.status == GenerationStatus.active,
            )
        )
        if collection_ids:
            neighbor_statement = neighbor_statement.where(
                Document.collection_id.in_(collection_ids)
            )
        neighbor_result = await session.execute(neighbor_statement)
        neighbors = {
            neighbor_id: text
            for neighbor_id, text in neighbor_result.all()
            if isinstance(text, str) and text.strip()
        }
    by_source_id = {uuid.UUID(source.chunk_id): source for source in sources}
    expanded: list[RetrievedSource] = []
    seen_units: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for chunk_id, row in rows.items():
        source = by_source_id[chunk_id]
        parent_id = row[6]
        parent_text = row[9]
        unit_id = parent_id or chunk_id
        key = (row[1], unit_id)
        if key in seen_units:
            continue
        seen_units.add(key)
        if parent_id is not None and parent_text:
            expanded.append(
                RetrievedSource(
                    document_id=source.document_id,
                    generation=source.generation,
                    chunk_id=source.chunk_id,
                    filename=source.filename,
                    chunk_text=parent_text,
                    score=source.score,
                    page_number=source.page_number,
                    section_heading=source.section_heading,
                    parent_id=str(parent_id),
                    supporting_chunk_ids=(source.chunk_id,),
                )
            )
        else:
            previous_text = neighbors.get(row[7])
            next_text = neighbors.get(row[8])
            expanded.append(
                RetrievedSource(
                    document_id=source.document_id,
                    generation=source.generation,
                    chunk_id=source.chunk_id,
                    filename=source.filename,
                    chunk_text="\n\n".join(
                        [
                            text
                            for text in (previous_text, source.chunk_text, next_text)
                            if text
                        ]
                    ),
                    score=source.score,
                    page_number=source.page_number,
                    section_heading=source.section_heading,
                    supporting_chunk_ids=(source.chunk_id,),
                )
            )
    return expanded


async def retrieve_sources(
    session: AsyncSession,
    *,
    settings: Settings,
    pinecone_client: Pinecone,
    query: str,
    user_id: uuid.UUID,
    collection_ids: list[uuid.UUID] | None = None,
    openai_client: AsyncOpenAI | None = None,
    reranker: Reranker | None = None,
) -> list[RetrievedSource]:
    """Query one owner namespace then prove each returned match is live in Postgres."""
    retrieval_started = time.perf_counter()
    selected_collections = collection_ids or []
    await _validate_collection_ids(
        session, user_id=user_id, collection_ids=selected_collections
    )
    dense_started = time.perf_counter()
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
        with DependencySpan("pinecone", "query"):
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    index.query,
                    vector=vector,
                    top_k=settings.chat_retrieval_top_k
                    * settings.chat_retrieval_overfetch,
                    namespace=embeddings.build_pinecone_namespace(user_id=user_id),
                    include_metadata=True,
                    filter=metadata_filter,
                ),
                timeout=settings.pinecone_query_timeout_seconds,
            )
    except ValueError:
        record_rag_stage_observation(
            stage="dense",
            outcome="validation_failure",
            duration_ms=(time.perf_counter() - dense_started) * 1000,
        )
        raise
    except Exception as exc:
        record_rag_stage_observation(
            stage="dense",
            outcome="failure",
            duration_ms=(time.perf_counter() - dense_started) * 1000,
        )
        raise RetrievalUnavailableError("Retrieval is temporarily unavailable") from exc

    record_rag_stage_observation(
        stage="dense",
        outcome="success",
        duration_ms=(time.perf_counter() - dense_started) * 1000,
    )

    matches = getattr(response, "matches", None)
    if matches is None and isinstance(response, Mapping):
        matches = response.get("matches", [])
    dense_candidates = _dense_candidates(list(matches or []))
    lexical_candidates: list[RetrievalCandidate] = []
    lexical_degraded = False
    selected_candidates: list[RetrievalCandidate] | list[FusedCandidate] = (
        dense_candidates
    )

    if settings.retrieval_mode != "dense":
        lexical_started = time.perf_counter()
        try:
            lexical_candidates = await retrieve_lexical_candidates(
                session=session,
                user_id=user_id,
                query=query,
                collection_ids=selected_collections,
                limit=settings.chat_retrieval_top_k * settings.chat_retrieval_overfetch,
            )
        except Exception as exc:
            if (
                settings.retrieval_mode == "hybrid"
                and settings.lexical_degradation_mode != "dense_only"
            ):
                record_rag_stage_observation(
                    stage="lexical",
                    outcome="failure",
                    duration_ms=(time.perf_counter() - lexical_started) * 1000,
                )
                raise RetrievalUnavailableError(
                    "Lexical retrieval is temporarily unavailable"
                ) from exc
            lexical_degraded = True
            record_rag_stage_observation(
                stage="lexical",
                outcome="degraded",
                duration_ms=(time.perf_counter() - lexical_started) * 1000,
                degraded=True,
            )
        else:
            record_rag_stage_observation(
                stage="lexical",
                outcome="success",
                duration_ms=(time.perf_counter() - lexical_started) * 1000,
            )
        fusion_started = time.perf_counter()
        fused = fuse_ranked_candidates(
            [*dense_candidates, *lexical_candidates],
            rrf_k=settings.retrieval_rrf_k,
            dense_weight=settings.retrieval_dense_weight,
            lexical_weight=settings.retrieval_lexical_weight,
        )
        if settings.retrieval_mode == "hybrid":
            selected_candidates = fused
        record_rag_stage_observation(
            stage="fusion",
            outcome="success",
            duration_ms=(time.perf_counter() - fusion_started) * 1000,
        )

    retrieval_event(
        logger,
        "retrieval_completed",
        mode=settings.retrieval_mode,
        dense_count=len(dense_candidates),
        selected_count=len(selected_candidates),
    )

    hydration_started = time.perf_counter()
    normalized = await _hydrate_active_chunks(
        session,
        user_id=user_id,
        candidates=selected_candidates,
    )
    lifecycle_excluded_count = max(len(selected_candidates) - len(normalized), 0)
    record_rag_stage_observation(
        stage="lifecycle_hydration",
        outcome="success",
        duration_ms=(time.perf_counter() - hydration_started) * 1000,
    )
    if settings.retrieval_expansion_enabled:
        expansion_started = time.perf_counter()
        source_count_before_expansion = len(normalized)
        normalized = await _expand_lifecycle_valid_sources(
            session,
            user_id=user_id,
            sources=normalized,
            collection_ids=selected_collections,
        )
        record_rag_stage_observation(
            stage="expansion",
            outcome="success",
            duration_ms=(time.perf_counter() - expansion_started) * 1000,
        )
        expansion_added_count = max(len(normalized) - source_count_before_expansion, 0)
    else:
        expansion_added_count = 0
    qualifying = (
        normalized
        if settings.retrieval_mode == "hybrid"
        else [
            source
            for source in normalized
            if source.score >= settings.chat_retrieval_score_threshold
        ]
    )
    qualifying.sort(key=lambda source: source.score, reverse=True)
    qualifying = qualifying[: settings.chat_retrieval_max_sources]
    reranking_count = 0
    if reranker is not None and (
        settings.reranking_enabled or settings.reranking_shadow_enabled
    ):
        reranking_count = len(qualifying)
        reranking_started = time.perf_counter()
        try:
            reranked = await apply_reranker(
                reranker=reranker, query=query, sources=qualifying
            )
        except Exception as exc:
            record_rag_stage_observation(
                stage="reranking",
                outcome="failure",
                duration_ms=(time.perf_counter() - reranking_started) * 1000,
            )
            if (
                settings.reranking_enabled
                and settings.lexical_degradation_mode == "fail"
            ):
                raise RetrievalUnavailableError(
                    "Reranking is temporarily unavailable"
                ) from exc
        else:
            if settings.reranking_enabled:
                qualifying = reranked
            record_rag_stage_observation(
                stage="reranking",
                outcome="success",
                duration_ms=(time.perf_counter() - reranking_started) * 1000,
            )
    fusion_overlap = sum(
        candidate.dense_rank is not None and candidate.lexical_rank is not None
        for candidate in selected_candidates
        if isinstance(candidate, FusedCandidate)
    )
    total_latency_ms = round((time.perf_counter() - retrieval_started) * 1000, 2)
    record_retrieval_observation(
        mode=settings.retrieval_mode,
        dense_count=len(dense_candidates),
        lexical_count=len(lexical_candidates),
        fusion_overlap=fusion_overlap,
        selected_count=len(selected_candidates),
        lifecycle_excluded_count=lifecycle_excluded_count,
        expansion_added_count=expansion_added_count,
        reranking_count=reranking_count,
        qualifying_count=len(qualifying),
        degraded=lexical_degraded,
        total_latency_ms=total_latency_ms,
    )
    record_rag_stage_observation(
        stage="evidence_selection",
        outcome="success",
        duration_ms=total_latency_ms,
        degraded=lexical_degraded,
    )
    return qualifying
