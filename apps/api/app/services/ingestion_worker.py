import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document, IngestionJob, IngestionStatus

logger = logging.getLogger(__name__)


class RetryableIngestionError(Exception):
    """Raised when ingestion processing can be retried safely."""


class NonRetryableIngestionError(Exception):
    """Raised when ingestion processing should be marked as failed."""


@dataclass(slots=True)
class ClaimedIngestionJob:
    job: IngestionJob
    document: Document


async def enqueue_ingestion_job(
    redis_client: Redis,
    *,
    queue_key: str,
    job_id: uuid.UUID,
) -> None:
    await redis_client.rpush(queue_key, str(job_id))


async def dequeue_ingestion_job(
    redis_client: Redis,
    *,
    queue_key: str,
    timeout_seconds: int,
) -> uuid.UUID | None:
    result = await redis_client.blpop(queue_key, timeout=timeout_seconds)
    if result is None:
        return None

    _key, value = result
    try:
        return uuid.UUID(value)
    except ValueError:
        logger.warning("Invalid ingestion job id in queue", extra={"raw_value": value})
        return None


async def claim_ingestion_job(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> ClaimedIngestionJob | None:
    result = await session.execute(
        select(IngestionJob, Document)
        .join(Document, Document.id == IngestionJob.document_id)
        .where(IngestionJob.id == job_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return None

    job, document = row
    if job.status != IngestionStatus.queued:
        await session.rollback()
        return None

    job.status = IngestionStatus.processing
    job.started_at = datetime.now(UTC)
    job.completed_at = None
    job.error = None
    job.attempts += 1
    document.status = IngestionStatus.processing

    await session.commit()
    await session.refresh(job)
    await session.refresh(document)
    return ClaimedIngestionJob(job=job, document=document)


async def claim_next_queued_ingestion_job(
    session: AsyncSession,
) -> ClaimedIngestionJob | None:
    result = await session.execute(
        select(IngestionJob, Document)
        .join(Document, Document.id == IngestionJob.document_id)
        .where(IngestionJob.status == IngestionStatus.queued)
        .order_by(IngestionJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return None

    job, document = row
    job.status = IngestionStatus.processing
    job.started_at = datetime.now(UTC)
    job.completed_at = None
    job.error = None
    job.attempts += 1
    document.status = IngestionStatus.processing

    await session.commit()
    await session.refresh(job)
    await session.refresh(document)
    return ClaimedIngestionJob(job=job, document=document)


async def mark_ingestion_job_ready(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> None:
    result = await session.execute(
        select(IngestionJob, Document)
        .join(Document, Document.id == IngestionJob.document_id)
        .where(IngestionJob.id == job_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return

    job, document = row
    job.status = IngestionStatus.ready
    job.completed_at = datetime.now(UTC)
    job.error = None
    document.status = IngestionStatus.ready
    await session.commit()


async def mark_ingestion_job_retry_or_failed(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    error_message: str,
    max_attempts: int,
) -> bool:
    """Return True when re-queued, False when moved to failed."""
    result = await session.execute(
        select(IngestionJob, Document)
        .join(Document, Document.id == IngestionJob.document_id)
        .where(IngestionJob.id == job_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return False

    job, document = row
    if job.attempts >= max_attempts:
        job.status = IngestionStatus.failed
        job.completed_at = datetime.now(UTC)
        document.status = IngestionStatus.failed
        requeued = False
    else:
        job.status = IngestionStatus.queued
        job.completed_at = None
        document.status = IngestionStatus.queued
        requeued = True

    job.error = error_message[:1000]
    await session.commit()
    return requeued


async def mark_ingestion_job_failed(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    error_message: str,
) -> None:
    result = await session.execute(
        select(IngestionJob, Document)
        .join(Document, Document.id == IngestionJob.document_id)
        .where(IngestionJob.id == job_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return

    job, document = row
    job.status = IngestionStatus.failed
    job.completed_at = datetime.now(UTC)
    job.error = error_message[:1000]
    document.status = IngestionStatus.failed
    await session.commit()


async def process_next_ingestion_job(
    session: AsyncSession,
    *,
    redis_client: Redis,
    queue_key: str,
    dequeue_timeout_seconds: int,
    max_attempts: int,
    processor,
) -> bool:
    job_id = await dequeue_ingestion_job(
        redis_client,
        queue_key=queue_key,
        timeout_seconds=dequeue_timeout_seconds,
    )

    if job_id is not None:
        claimed = await claim_ingestion_job(session, job_id=job_id)
    else:
        claimed = await claim_next_queued_ingestion_job(session)

    if claimed is None:
        return False

    try:
        await processor(claimed)
        await mark_ingestion_job_ready(session, job_id=claimed.job.id)
        return True
    except RetryableIngestionError as exc:
        requeued = await mark_ingestion_job_retry_or_failed(
            session,
            job_id=claimed.job.id,
            error_message=str(exc),
            max_attempts=max_attempts,
        )
        if requeued:
            await enqueue_ingestion_job(
                redis_client,
                queue_key=queue_key,
                job_id=claimed.job.id,
            )
        return True
    except NonRetryableIngestionError as exc:
        await mark_ingestion_job_failed(
            session,
            job_id=claimed.job.id,
            error_message=str(exc),
        )
        return True
    except Exception:
        logger.exception(
            "Unexpected ingestion worker error",
            extra={"job_id": str(claimed.job.id)},
        )
        requeued = await mark_ingestion_job_retry_or_failed(
            session,
            job_id=claimed.job.id,
            error_message="Unexpected ingestion processing error",
            max_attempts=max_attempts,
        )
        if requeued:
            await enqueue_ingestion_job(
                redis_client,
                queue_key=queue_key,
                job_id=claimed.job.id,
            )
        return True
