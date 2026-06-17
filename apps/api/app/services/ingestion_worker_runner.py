import asyncio
import logging

import redis.asyncio as redis
from openai import AsyncOpenAI
from pinecone import Pinecone
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.services import (
    contextual_chunking,
    document_processor,
    embeddings,
    ingestion_worker,
)

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
pinecone_client = Pinecone(api_key=settings.pinecone_api_key)
openai_client = (
    AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
)


async def _embed_chunks_with_retry(chunks, *, max_attempts: int = 3):
    for attempt in range(1, max_attempts + 1):
        try:
            return await embeddings.embed_chunks(
                provider=settings.embedding_provider,
                chunks=chunks,
                model=settings.embedding_model,
                input_type=settings.embedding_input_type,
                pinecone_client=pinecone_client,
                openai_client=openai_client,
            )
        except Exception as exc:
            if attempt >= max_attempts:
                raise ingestion_worker.RetryableIngestionError(
                    f"Embedding generation failed after retries: {exc}"
                ) from exc
            await asyncio.sleep(0.5 * attempt)


async def _upsert_embeddings_with_retry(
    *,
    namespace: str,
    embedded_chunks,
    max_attempts: int = 3,
) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            embeddings.upsert_embeddings(
                pinecone_client,
                index_name=settings.pinecone_index_name,
                namespace=namespace,
                embedded_chunks=embedded_chunks,
            )
            return
        except Exception as exc:
            if attempt >= max_attempts:
                raise ingestion_worker.RetryableIngestionError(
                    f"Vector upsert failed after retries: {exc}"
                ) from exc
            await asyncio.sleep(0.5 * attempt)


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

    document_text = "\n\n".join(
        segment.text for segment in segments if segment.text.strip()
    )
    contextualized_lookup: dict[int, str] = {}

    if settings.contextual_embedding_enabled and document_text:
        if settings.contextual_chunking_provider == "openai":
            if openai_client is None or not settings.contextual_chunking_model:
                raise ingestion_worker.NonRetryableIngestionError(
                    "OpenAI contextual chunking is enabled but not configured correctly"
                )

            for chunk in chunks:
                contextualized_lookup[
                    chunk.chunk_index
                ] = await contextual_chunking.situate_chunk_with_openai(
                    openai_client,
                    document_text=document_text,
                    chunk_text=chunk.chunk_text,
                    model=settings.contextual_chunking_model,
                )
        else:
            contextualized_chunks = document_processor.build_contextualized_chunks(
                segments=segments,
                source_file=claimed_job.document.filename,
            )
            contextualized_lookup = {
                chunk.chunk_index: chunk.contextualized_text
                for chunk in contextualized_chunks
                if chunk.contextualized_text
            }

    await document_processor.replace_document_chunks(
        session,
        document_id=claimed_job.document.id,
        chunks=chunks,
    )

    persisted_chunks = await document_processor.list_document_chunks(
        session,
        document_id=claimed_job.document.id,
    )

    chunks_for_embedding = []
    if settings.contextual_embedding_enabled:
        for persisted_chunk in persisted_chunks:
            contextualized_text = contextualized_lookup.get(persisted_chunk.chunk_index)
            if contextualized_text:
                persisted_chunk.chunk_text = contextualized_text
            chunks_for_embedding.append(persisted_chunk)
    else:
        chunks_for_embedding = persisted_chunks

    embedded_chunks = await _embed_chunks_with_retry(
        chunks_for_embedding,
    )

    namespace = embeddings.build_pinecone_namespace(
        user_id=claimed_job.document.user_id
    )
    await _upsert_embeddings_with_retry(
        namespace=namespace,
        embedded_chunks=embedded_chunks,
    )

    embedded_lookup = {item.chunk_id: item.vector_id for item in embedded_chunks}
    for chunk_row in persisted_chunks:
        chunk_row.vector_id = embedded_lookup.get(chunk_row.id)

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
