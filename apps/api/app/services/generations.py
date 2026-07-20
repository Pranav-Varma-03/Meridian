"""Transactional lifecycle transitions for document ingestion generations."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Document,
    DocumentIngestionGeneration,
    GenerationStatus,
    GenerationVectorManifest,
    IngestionStatus,
    OutboxEvent,
    PurgeJob,
    PurgeJobStatus,
)


async def activate_generation(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    generation_id: uuid.UUID,
    vector_ids: list[str],
) -> None:
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
    if document is None or generation is None or generation.document_id != document.id:
        raise ValueError("Generation does not belong to document")

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
