"""Transactional lifecycle transitions for document ingestion generations."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Document,
    DocumentChunk,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    DocumentParentWindow,
    GenerationStatus,
    GenerationVectorManifest,
    IngestionJob,
    IngestionStatus,
    OutboxEvent,
    PurgeJob,
    PurgeJobStatus,
)
from app.services.structured_ingestion import uses_structured_generation


async def ensure_generation_activation_ready(
    session: AsyncSession,
    *,
    generation: DocumentIngestionGeneration,
    vector_ids: list[str],
) -> None:
    """Fence structured generations until every derived retrieval record exists."""
    if not uses_structured_generation(getattr(generation, "configuration_json", None)):
        return
    await session.flush()
    parent_count = await session.scalar(
        select(func.count(DocumentParentWindow.id)).where(
            DocumentParentWindow.generation_id == generation.id
        )
    )
    child_count = await session.scalar(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.generation_id == generation.id
        )
    )
    complete_child_count = await session.scalar(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.generation_id == generation.id,
            DocumentChunk.parent_id.is_not(None),
            DocumentChunk.embedding_text.is_not(None),
            DocumentChunk.lexical_search.is_not(None),
            DocumentChunk.vector_id.is_not(None),
        )
    )
    expected = int(child_count or 0)
    if (
        int(parent_count or 0) <= 0
        or expected <= 0
        or int(complete_child_count or 0) != expected
        or len(set(vector_ids)) != expected
    ):
        raise ValueError("Structured generation is incomplete and cannot activate")


async def activate_generation(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    generation_id: uuid.UUID,
    vector_ids: list[str],
    job_id: uuid.UUID | None = None,
) -> bool:
    """Make a fully-upserted generation retrievable and queue old-vector purge.

    This is deliberately performed only after Pinecone accepted the new vectors.
    The prior active generation remains queryable until this database transaction
    succeeds, which avoids a retrieval gap during re-ingestion.
    """
    document = await session.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    generation = await session.scalar(
        select(DocumentIngestionGeneration)
        .where(DocumentIngestionGeneration.id == generation_id)
        .with_for_update()
    )
    job = None
    if job_id is not None:
        job = await session.scalar(
            select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()
        )
    if document is None or generation is None or generation.document_id != document.id:
        raise ValueError("Generation does not belong to document")
    if (
        document.lifecycle_status != DocumentLifecycleStatus.active
        or generation.status != GenerationStatus.pending
        or (
            job is not None
            and (
                job.document_id != document.id
                or job.generation_id != generation.id
                or job.status != IngestionStatus.processing
            )
        )
    ):
        # The provider write may have completed before a concurrent delete became
        # visible. Preserve a durable compensating purge instead of activating it.
        if generation.status == GenerationStatus.pending:
            generation.status = GenerationStatus.failed
            generation.error = "Generation activation fenced by document lifecycle"
        existing_purge = await session.scalar(
            select(PurgeJob.id).where(
                PurgeJob.idempotency_key == f"failed-generation-purge:{generation.id}"
            )
        )
        if existing_purge is None and generation.status != GenerationStatus.active:
            purge_job = PurgeJob(
                document_id=document.id,
                generation_id=generation.id,
                status=PurgeJobStatus.queued,
                idempotency_key=f"failed-generation-purge:{generation.id}",
            )
            session.add(purge_job)
            await session.flush()
            session.add(
                OutboxEvent(
                    topic="failed_document_generation_purge",
                    payload_json={"purge_job_id": str(purge_job.id)},
                )
            )
        await session.commit()
        return False

    await ensure_generation_activation_ready(
        session, generation=generation, vector_ids=vector_ids
    )

    previous_generation_id = document.active_generation_id
    for vector_id in dict.fromkeys(vector_ids):
        session.add(
            GenerationVectorManifest(generation_id=generation.id, vector_id=vector_id)
        )

    if previous_generation_id and previous_generation_id != generation.id:
        previous = await session.scalar(
            select(DocumentIngestionGeneration).where(
                DocumentIngestionGeneration.id == previous_generation_id
            )
        )
        if previous is not None:
            previous.status = GenerationStatus.superseded
            purge_job = PurgeJob(
                document_id=document.id,
                generation_id=previous.id,
                status=PurgeJobStatus.queued,
                idempotency_key=f"generation-purge:{previous.id}",
            )
            session.add(purge_job)
            await session.flush()
            session.add(
                OutboxEvent(
                    topic="document_generation_purge",
                    payload_json={"purge_job_id": str(purge_job.id)},
                )
            )

    generation.status = GenerationStatus.active
    generation.error = None
    generation.activated_at = datetime.now(UTC)
    document.active_generation_id = generation.id
    # `documents.status` remains the legacy/UI-facing ingestion state. Keep it
    # synchronized with the active generation so a completed first ingestion
    # is never displayed as permanently processing.
    document.status = IngestionStatus.ready
    await session.commit()
    return True
