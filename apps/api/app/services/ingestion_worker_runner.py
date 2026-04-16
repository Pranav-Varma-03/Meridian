import asyncio
import logging

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.services import document_processor, ingestion_worker

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def default_ingestion_processor(
    session: AsyncSession,
    claimed_job: ingestion_worker.ClaimedIngestionJob,
) -> None:
    """Parse document text, chunk it, and persist chunk metadata."""
    metadata = claimed_job.document.metadata_json or {}
    storage_path = metadata.get("storage_path")
    if not isinstance(storage_path, str) or not storage_path:
        raise ingestion_worker.NonRetryableIngestionError(
            "Document storage path is missing"
        )

    try:
        segments = document_processor.extract_text_segments(
            storage_path=storage_path,
            mime_type=claimed_job.document.mime_type,
        )
    except (OSError, ValueError) as exc:
        raise ingestion_worker.NonRetryableIngestionError(
            f"Unable to parse document content: {exc}"
        ) from exc

    if not segments:
        raise ingestion_worker.NonRetryableIngestionError(
            "No extractable text found in document"
        )

    chunks = document_processor.build_chunks(
        segments=segments,
        source_file=claimed_job.document.filename,
    )
    if not chunks:
        raise ingestion_worker.NonRetryableIngestionError(
            "Chunk generation produced no output"
        )

    await document_processor.replace_document_chunks(
        session,
        document_id=claimed_job.document.id,
        chunks=chunks,
    )

    logger.info(
        "processing_ingestion_job",
        extra={
            "job_id": str(claimed_job.job.id),
            "document_id": str(claimed_job.document.id),
            "attempts": claimed_job.job.attempts,
            "chunk_count": len(chunks),
        },
    )


async def run_worker_loop() -> None:
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    await redis_client.ping()

    logger.info(
        "ingestion_worker_started",
        extra={
            "queue_key": settings.ingestion_queue_key,
            "dequeue_timeout_seconds": settings.ingestion_worker_dequeue_timeout_seconds,
            "max_attempts": settings.ingestion_worker_max_attempts,
        },
    )

    try:
        while True:
            async with AsyncSessionLocal() as session:
                processed = await ingestion_worker.process_next_ingestion_job(
                    session,
                    redis_client=redis_client,
                    queue_key=settings.ingestion_queue_key,
                    dequeue_timeout_seconds=settings.ingestion_worker_dequeue_timeout_seconds,
                    max_attempts=settings.ingestion_worker_max_attempts,
                    processor=default_ingestion_processor,
                )

            if not processed:
                await asyncio.sleep(settings.ingestion_worker_idle_sleep_seconds)
    finally:
        await redis_client.aclose()


def main() -> None:
    asyncio.run(run_worker_loop())


if __name__ == "__main__":
    main()
