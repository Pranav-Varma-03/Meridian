import asyncio
import logging

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.services import ingestion_worker

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def default_ingestion_processor(
    claimed_job: ingestion_worker.ClaimedIngestionJob,
) -> None:
    """Placeholder processor until parse/chunk/embed pipeline wiring is complete."""
    logger.info(
        "processing_ingestion_job",
        extra={
            "job_id": str(claimed_job.job.id),
            "document_id": str(claimed_job.document.id),
            "attempts": claimed_job.job.attempts,
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
