import logging
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Document,
    DocumentIngestionGeneration,
    DocumentLifecycleStatus,
    GenerationStatus,
    IngestionJob,
    IngestionStatus,
    OutboxEvent,
    PurgeJob,
    PurgeJobStatus,
)

logger = logging.getLogger(__name__)


class RetryableIngestionError(Exception):
    """Raised when ingestion processing can be retried safely."""


class NonRetryableIngestionError(Exception):
    """Raised when ingestion processing should be marked as failed."""


@dataclass(slots=True)
class ClaimedIngestionJob:
    job: IngestionJob
    document: Document
    generation: DocumentIngestionGeneration


async def _ensure_generation_purge(
    session: AsyncSession,
    *,
    document: Document,
    generation: DocumentIngestionGeneration,
) -> None:
    """Retain one durable cleanup owner for a non-active generation."""
    idempotency_key = f"failed-generation-purge:{generation.id}"
    existing = await session.scalar(
        select(PurgeJob.id).where(PurgeJob.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return
    cleanup_job = PurgeJob(
        document_id=document.id,
        generation_id=generation.id,
        status=PurgeJobStatus.queued,
        idempotency_key=idempotency_key,
    )
    session.add(cleanup_job)
    await session.flush()
    session.add(
        OutboxEvent(
            topic="failed_document_generation_purge",
            payload_json={"purge_job_id": str(cleanup_job.id)},
        )
    )


async def _terminalize_for_lifecycle_fence(
    session: AsyncSession,
    *,
    job: IngestionJob,
    document: Document,
    generation: DocumentIngestionGeneration,
    error_message: str,
) -> None:
    """Stop a job that can no longer safely write or activate vectors."""
    job.status = IngestionStatus.failed
    job.completed_at = datetime.now(UTC)
    job.started_at = None
    job.next_attempt_at = None
    job.error = error_message[:1000]
    if generation.status == GenerationStatus.pending:
        generation.status = GenerationStatus.failed
        generation.error = error_message[:1000]
    if generation.status != GenerationStatus.active:
        await _ensure_generation_purge(
            session, document=document, generation=generation
        )
    if (
        document.active_generation_id is None
        and document.lifecycle_status == DocumentLifecycleStatus.active
    ):
        document.status = IngestionStatus.failed


def _is_processable(
    job: IngestionJob,
    document: Document,
    generation: DocumentIngestionGeneration,
) -> bool:
    return (
        job.status == IngestionStatus.processing
        and document.lifecycle_status == DocumentLifecycleStatus.active
        and generation.status == GenerationStatus.pending
    )


async def ensure_claimed_job_processable(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> bool:
    """Re-check lifecycle state immediately before an external provider write."""
    result = await session.execute(
        select(IngestionJob, Document, DocumentIngestionGeneration)
        .join(Document, Document.id == IngestionJob.document_id)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == IngestionJob.generation_id,
        )
        .where(IngestionJob.id == job_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return False
    job, document, generation = row
    if _is_processable(job, document, generation):
        # Commit releases the short row lock before a potentially slow provider call.
        await session.commit()
        return True

    await _terminalize_for_lifecycle_fence(
        session,
        job=job,
        document=document,
        generation=generation,
        error_message="Ingestion fenced by document lifecycle transition",
    )
    await session.commit()
    logger.info(
        "ingestion_lifecycle_fenced",
        extra={
            "job_id": str(job.id),
            "document_id": str(document.id),
            "generation_id": str(generation.id),
            "failure_class": "lifecycle_fence",
        },
    )
    return False


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
    try:
        result = await redis_client.blpop(queue_key, timeout=timeout_seconds)
    except RedisError as exc:
        # Redis is only a wake-up channel. A transient blocking-read timeout
        # must not stop the worker because queued Postgres jobs are claimed by
        # the durable fallback immediately below.
        logger.warning(
            "ingestion_queue_unavailable_using_database_fallback",
            extra={"error_type": type(exc).__name__},
        )
        return None
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
        select(IngestionJob, Document, DocumentIngestionGeneration)
        .join(Document, Document.id == IngestionJob.document_id)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == IngestionJob.generation_id,
        )
        .where(IngestionJob.id == job_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return None

    job, document, generation = row
    if job.status != IngestionStatus.queued:
        await session.rollback()
        return None
    if (
        document.lifecycle_status != DocumentLifecycleStatus.active
        or generation.status != GenerationStatus.pending
    ):
        await _terminalize_for_lifecycle_fence(
            session,
            job=job,
            document=document,
            generation=generation,
            error_message="Ingestion claim fenced by document lifecycle transition",
        )
        await session.commit()
        return None

    job.status = IngestionStatus.processing
    job.next_attempt_at = None
    job.started_at = datetime.now(UTC)
    job.completed_at = None
    job.error = None
    job.attempts += 1
    if document.active_generation_id is None:
        document.status = IngestionStatus.processing

    await session.commit()
    await session.refresh(job)
    await session.refresh(document)
    await session.refresh(generation)
    return ClaimedIngestionJob(job=job, document=document, generation=generation)


async def claim_next_queued_ingestion_job(
    session: AsyncSession,
) -> ClaimedIngestionJob | None:
    result = await session.execute(
        select(IngestionJob, Document, DocumentIngestionGeneration)
        .join(Document, Document.id == IngestionJob.document_id)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == IngestionJob.generation_id,
        )
        .where(IngestionJob.status == IngestionStatus.queued)
        .where(
            or_(
                IngestionJob.next_attempt_at.is_(None),
                IngestionJob.next_attempt_at <= datetime.now(UTC),
            )
        )
        .order_by(IngestionJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return None

    job, document, generation = row
    if (
        document.lifecycle_status != DocumentLifecycleStatus.active
        or generation.status != GenerationStatus.pending
    ):
        await _terminalize_for_lifecycle_fence(
            session,
            job=job,
            document=document,
            generation=generation,
            error_message="Ingestion claim fenced by document lifecycle transition",
        )
        await session.commit()
        return None
    job.status = IngestionStatus.processing
    job.next_attempt_at = None
    job.started_at = datetime.now(UTC)
    job.completed_at = None
    job.error = None
    job.attempts += 1
    if document.active_generation_id is None:
        document.status = IngestionStatus.processing

    await session.commit()
    await session.refresh(job)
    await session.refresh(document)
    await session.refresh(generation)
    return ClaimedIngestionJob(job=job, document=document, generation=generation)


async def mark_ingestion_job_ready(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
) -> None:
    result = await session.execute(
        select(IngestionJob, Document, DocumentIngestionGeneration)
        .join(Document, Document.id == IngestionJob.document_id)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == IngestionJob.generation_id,
        )
        .where(IngestionJob.id == job_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return

    job, document, generation = row
    job.status = IngestionStatus.ready
    job.completed_at = datetime.now(UTC)
    job.error = None
    # This is a compatibility safeguard for legacy jobs and for callers that
    # finalize a job independently of generation activation. Re-ingestion never
    # makes an already-ready document unavailable because claiming only changes
    # this status when there is no active generation.
    if document.lifecycle_status == DocumentLifecycleStatus.active:
        document.status = IngestionStatus.ready
    await session.commit()


async def mark_ingestion_job_retry_or_failed(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    error_message: str,
    max_attempts: int,
    retry_base_seconds: float = 1.0,
    retry_max_seconds: float = 300.0,
) -> bool:
    """Return True when re-queued, False when moved to failed."""
    result = await session.execute(
        select(IngestionJob, Document, DocumentIngestionGeneration)
        .join(Document, Document.id == IngestionJob.document_id)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == IngestionJob.generation_id,
        )
        .where(IngestionJob.id == job_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return False

    job, document, generation = row
    if job.attempts >= max_attempts:
        job.status = IngestionStatus.failed
        job.completed_at = datetime.now(UTC)
        job.next_attempt_at = None
        generation.status = GenerationStatus.failed
        await _ensure_generation_purge(
            session, document=document, generation=generation
        )
        if document.active_generation_id is None:
            document.status = IngestionStatus.failed
        requeued = False
    else:
        job.status = IngestionStatus.queued
        job.completed_at = None
        delay_ceiling = min(
            retry_max_seconds, retry_base_seconds * (2 ** (job.attempts - 1))
        )
        # Full jitter avoids a synchronized retry storm when an upstream provider
        # recovers after a shared outage.
        job.next_attempt_at = datetime.now(UTC) + timedelta(
            seconds=random.uniform(0, delay_ceiling)
        )
        if document.active_generation_id is None:
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
        select(IngestionJob, Document, DocumentIngestionGeneration)
        .join(Document, Document.id == IngestionJob.document_id)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == IngestionJob.generation_id,
        )
        .where(IngestionJob.id == job_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        await session.rollback()
        return

    job, document, generation = row
    job.status = IngestionStatus.failed
    job.completed_at = datetime.now(UTC)
    job.next_attempt_at = None
    job.error = error_message[:1000]
    generation.status = GenerationStatus.failed
    await _ensure_generation_purge(session, document=document, generation=generation)
    if document.active_generation_id is None:
        document.status = IngestionStatus.failed
    await session.commit()


async def recover_stuck_ingestion_jobs(
    session: AsyncSession,
    *,
    stuck_timeout_seconds: float,
    max_attempts: int,
    retry_base_seconds: float,
    retry_max_seconds: float,
) -> int:
    """Recover jobs stranded in processing after a worker process disappears."""
    cutoff = datetime.now(UTC) - timedelta(seconds=stuck_timeout_seconds)
    result = await session.execute(
        select(IngestionJob, Document, DocumentIngestionGeneration)
        .join(Document, Document.id == IngestionJob.document_id)
        .join(
            DocumentIngestionGeneration,
            DocumentIngestionGeneration.id == IngestionJob.generation_id,
        )
        .where(
            IngestionJob.status == IngestionStatus.processing,
            IngestionJob.started_at <= cutoff,
        )
        .with_for_update(skip_locked=True)
    )
    recovered = 0
    for job, document, generation in result.all():
        recovered += 1
        if (
            document.lifecycle_status == DocumentLifecycleStatus.active
            and document.active_generation_id == generation.id
            and generation.status == GenerationStatus.active
        ):
            job.status = IngestionStatus.ready
            job.completed_at = datetime.now(UTC)
            job.started_at = None
            job.error = None
            document.status = IngestionStatus.ready
        elif (
            document.lifecycle_status == DocumentLifecycleStatus.active
            and generation.status == GenerationStatus.pending
            and job.attempts < max_attempts
        ):
            job.status = IngestionStatus.queued
            job.started_at = None
            delay_ceiling = min(
                retry_max_seconds,
                retry_base_seconds * (2 ** max(job.attempts - 1, 0)),
            )
            job.next_attempt_at = datetime.now(UTC) + timedelta(
                seconds=random.uniform(0, delay_ceiling)
            )
            job.error = "Ingestion worker claim exceeded configured timeout"
            if document.active_generation_id is None:
                document.status = IngestionStatus.queued
        else:
            await _terminalize_for_lifecycle_fence(
                session,
                job=job,
                document=document,
                generation=generation,
                error_message="Stale ingestion job cannot be safely resumed",
            )
    if recovered:
        await session.commit()
        logger.warning(
            "ingestion_worker_recovered_stuck_jobs", extra={"count": recovered}
        )
    else:
        await session.rollback()
    return recovered


async def process_next_ingestion_job(
    session: AsyncSession,
    *,
    redis_client: Redis,
    queue_key: str,
    dequeue_timeout_seconds: int,
    max_attempts: int,
    processor,
    retry_base_seconds: float = 1.0,
    retry_max_seconds: float = 300.0,
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

    claimed_job_id = claimed.job.id

    try:
        await processor(session, claimed)
        await mark_ingestion_job_ready(session, job_id=claimed_job_id)
        return True
    except RetryableIngestionError as exc:
        await session.rollback()
        requeued = await mark_ingestion_job_retry_or_failed(
            session,
            job_id=claimed_job_id,
            error_message=str(exc),
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )
        if requeued:
            try:
                await enqueue_ingestion_job(
                    redis_client,
                    queue_key=queue_key,
                    job_id=claimed_job_id,
                )
            except RedisError as enqueue_exc:
                logger.warning(
                    "ingestion_retry_queue_unavailable",
                    extra={"error_type": type(enqueue_exc).__name__},
                )
        return True
    except NonRetryableIngestionError as exc:
        await session.rollback()
        await mark_ingestion_job_failed(
            session,
            job_id=claimed_job_id,
            error_message=str(exc),
        )
        return True
    except Exception:
        await session.rollback()
        logger.exception(
            "Unexpected ingestion worker error",
            extra={"job_id": str(claimed_job_id)},
        )
        requeued = await mark_ingestion_job_retry_or_failed(
            session,
            job_id=claimed_job_id,
            error_message="Unexpected ingestion processing error",
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )
        if requeued:
            try:
                await enqueue_ingestion_job(
                    redis_client,
                    queue_key=queue_key,
                    job_id=claimed_job_id,
                )
            except RedisError as enqueue_exc:
                logger.warning(
                    "ingestion_retry_queue_unavailable",
                    extra={"error_type": type(enqueue_exc).__name__},
                )
        return True
