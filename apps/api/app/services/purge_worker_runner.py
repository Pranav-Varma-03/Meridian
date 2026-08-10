"""Run the durable document/vector purge worker."""

import asyncio
import logging

from pinecone import Pinecone

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.observability import (
    SecretSafeJsonFormatter,
    initialize_observability,
    record_worker_heartbeat,
)
from app.services import purge_worker

settings = get_settings()
_handler = logging.StreamHandler()
_handler.setFormatter(SecretSafeJsonFormatter())
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    handlers=[_handler],
    force=True,
)
logger = logging.getLogger(__name__)
initialize_observability(settings)
pinecone_client = Pinecone(api_key=settings.pinecone_api_key)


async def run_worker_loop() -> None:
    while True:
        record_worker_heartbeat(worker="purge")
        async with AsyncSessionLocal() as session:
            recovered = await purge_worker.recover_stuck_purge_jobs(
                session,
                stuck_timeout_seconds=settings.purge_worker_stuck_timeout_seconds,
            )
            if recovered:
                logger.warning(
                    "purge_worker_recovered_stuck_jobs", extra={"count": recovered}
                )
            job = await purge_worker.claim_next_purge_job(session)
            if job is not None:
                await purge_worker.process_purge_job(
                    session,
                    job=job,
                    pinecone_client=pinecone_client,
                    pinecone_index_name=settings.pinecone_index_name,
                    batch_size=settings.pinecone_vector_delete_batch_size,
                    timeout_seconds=settings.pinecone_vector_delete_timeout_seconds,
                    max_attempts=settings.pinecone_vector_delete_max_attempts,
                )
        if job is None:
            await asyncio.sleep(settings.ingestion_worker_idle_sleep_seconds)


def main() -> None:
    asyncio.run(run_worker_loop())


if __name__ == "__main__":
    main()
