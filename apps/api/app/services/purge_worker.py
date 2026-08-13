"""Durable cleanup of superseded and logically deleted document vectors."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import (
    classify_provider_failure,
    lifecycle_event,
    record_worker_job_observation,
)
from app.models.entities import (
    Document,
    DocumentChunk,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    DocumentParentWindow,
    GenerationStatus,
    GenerationVectorManifest,
    PurgeJob,
    PurgeJobStatus,
)
from app.services import embeddings
from app.services.structured_ingestion import uses_structured_generation

logger = logging.getLogger(__name__)


async def claim_next_purge_job(session: AsyncSession) -> PurgeJob | None:
    job = await session.scalar(
        select(PurgeJob)
        .where(PurgeJob.status.in_([PurgeJobStatus.queued, PurgeJobStatus.retryable]))
        .where(
            or_(
                PurgeJob.next_attempt_at.is_(None),
                PurgeJob.next_attempt_at <= datetime.now(UTC),
            )
        )
        .order_by(PurgeJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        await session.rollback()
        return None
    job.status = PurgeJobStatus.running
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    job.next_attempt_at = None
    job.last_error = None
    await session.commit()
    await session.refresh(job)
    return job


async def recover_stuck_purge_jobs(
    session: AsyncSession,
    *,
    stuck_timeout_seconds: float,
) -> int:
    """Return abandoned running jobs to the durable retry queue.

    A worker can disappear after claiming a row. Its transaction already marked
    the job ``running``, so another worker must explicitly recover it rather than
    treating it as complete.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=stuck_timeout_seconds)
    result = await session.execute(
        update(PurgeJob)
        .where(
            PurgeJob.status == PurgeJobStatus.running,
            PurgeJob.started_at <= cutoff,
        )
        .values(
            status=PurgeJobStatus.retryable,
            started_at=None,
            next_attempt_at=datetime.now(UTC),
            last_error="Purge worker claim exceeded configured timeout",
        )
    )
    await session.commit()
    return int(result.rowcount or 0)


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
        record_worker_job_observation(
            worker="purge", operation="purge", outcome="complete"
        )
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
        if job.generation_id:
            generation = await session.scalar(
                select(DocumentIngestionGeneration).where(
                    DocumentIngestionGeneration.id == job.generation_id
                )
            )
            if generation is not None:
                await embeddings.delete_embeddings_by_metadata_filter(
                    pinecone_client,  # type: ignore[arg-type]
                    index_name=pinecone_index_name,
                    namespace=namespace,
                    metadata_filter={
                        "document_id": str(document.id),
                        "generation": generation.generation_number,
                    },
                    timeout_seconds=timeout_seconds,
                    max_attempts=max_attempts,
                )
        else:
            # A document-level filter is safe only after logical deletion; this
            # catches legacy vectors that predate generation manifests.
            await embeddings.delete_embeddings_by_metadata_filter(
                pinecone_client,  # type: ignore[arg-type]
                index_name=pinecone_index_name,
                namespace=namespace,
                metadata_filter={"document_id": str(document.id)},
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
        job.started_at = None
        if exc.retryable:
            job.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 2**job.attempts)
            )
        await session.commit()
        lifecycle_event(
            logger,
            "purge_job_retryable" if exc.retryable else "purge_job_terminal_failed",
            level=logging.WARNING,
            count=len(vector_ids),
            attempts=job.attempts,
            failure_class=classify_provider_failure(exc.__cause__ or exc),
            error_type=type(exc.__cause__ or exc).__name__,
            outcome="retryable" if exc.retryable else "terminal_failed",
        )
        record_worker_job_observation(
            worker="purge",
            operation="purge",
            outcome="retryable" if exc.retryable else "terminal_failed",
            failure_class=classify_provider_failure(exc.__cause__ or exc),
        )
        return

    if job.generation_id:
        generation = await session.scalar(
            select(DocumentIngestionGeneration).where(
                DocumentIngestionGeneration.id == job.generation_id
            )
        )
        if generation is not None:
            if uses_structured_generation(
                getattr(generation, "configuration_json", None)
            ):
                # Remove only the failed/superseded generation's relational state.
                # The prior active generation has a different generation ID and is
                # therefore unaffected by this compensation step.
                await session.execute(
                    delete(DocumentChunk).where(
                        DocumentChunk.generation_id == generation.id
                    )
                )
                await session.execute(
                    delete(DocumentParentWindow).where(
                        DocumentParentWindow.generation_id == generation.id
                    )
                )
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
    job.started_at = None
    job.completed_at = datetime.now(UTC)
    await session.commit()
    lifecycle_event(
        logger,
        "purge_job_complete",
        count=len(vector_ids),
        attempts=job.attempts,
        outcome="complete",
    )
    record_worker_job_observation(worker="purge", operation="purge", outcome="complete")
