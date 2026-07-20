"""Durable cleanup of superseded and logically deleted document vectors."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Document,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    GenerationStatus,
    GenerationVectorManifest,
    PurgeJob,
    PurgeJobStatus,
)
from app.services import embeddings


async def claim_next_purge_job(session: AsyncSession) -> PurgeJob | None:
    job = await session.scalar(
        select(PurgeJob)
        .where(PurgeJob.status.in_([PurgeJobStatus.queued, PurgeJobStatus.retryable]))
        .order_by(PurgeJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        await session.rollback()
        return None
    job.status = PurgeJobStatus.running
    job.attempts += 1
    job.last_error = None
    await session.commit()
    await session.refresh(job)
    return job


async def process_purge_job(
    session: AsyncSession,
    *,
    job: PurgeJob,
    pinecone_client: object,
    pinecone_index_name: str,
    batch_size: int,
    timeout_seconds: float,
    max_attempts: int,
) -> None:
    document = await session.scalar(
        select(Document).where(Document.id == job.document_id)
    )
    if document is None:
        job.status = PurgeJobStatus.complete
        job.completed_at = datetime.now(UTC)
        await session.commit()
        return

    generation_ids = (
        [job.generation_id]
        if job.generation_id
        else list(
            await session.scalars(
                select(DocumentIngestionGeneration.id).where(
                    DocumentIngestionGeneration.document_id == document.id
                )
            )
        )
    )
    vector_ids = (
        list(
            await session.scalars(
                select(GenerationVectorManifest.vector_id).where(
                    GenerationVectorManifest.generation_id.in_(generation_ids)
                )
            )
        )
        if generation_ids
        else []
    )

    namespace = embeddings.build_pinecone_namespace(user_id=document.user_id)
    try:
        await embeddings.delete_embeddings(
            pinecone_client,  # type: ignore[arg-type]
            index_name=pinecone_index_name,
            namespace=namespace,
            vector_ids=vector_ids,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
    except embeddings.VectorDeletionError as exc:
        job.last_error = "Pinecone vector deletion failed"
        job.status = (
            PurgeJobStatus.retryable
            if exc.retryable
            else PurgeJobStatus.terminal_failed
        )
        if exc.retryable:
            job.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 2**job.attempts)
            )
        await session.commit()
        return

    if job.generation_id:
        generation = await session.scalar(
            select(DocumentIngestionGeneration).where(
                DocumentIngestionGeneration.id == job.generation_id
            )
        )
        if generation is not None:
            generation.status = GenerationStatus.purged
    else:
        metadata = document.metadata_json or {}
        storage_path = metadata.get("storage_path")
        if isinstance(storage_path, str):
            path = Path(storage_path)
            if path.is_file():
                path.unlink()
        document.lifecycle_status = DocumentLifecycleStatus.deleted

    job.status = PurgeJobStatus.complete
    job.completed_at = datetime.now(UTC)
    await session.commit()
