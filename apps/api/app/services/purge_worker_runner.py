"""Run the durable document/vector purge worker."""

import asyncio
import logging

from pinecone import Pinecone

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.observability import (
    configure_application_logging,
    initialize_observability,
    lifecycle_event,
    record_worker_heartbeat,
    shutdown_observability,
)
from app.services import purge_worker

settings = get_settings()
configure_application_logging(settings.log_level)
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
                lifecycle_event(
                    logger,
                    "purge_worker_recovered_stuck_jobs",
                    level=logging.WARNING,
                    count=recovered,
                    outcome="recovered",
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
    try:
        asyncio.run(run_worker_loop())
    finally:
        shutdown_observability()


if __name__ == "__main__":
    main()
