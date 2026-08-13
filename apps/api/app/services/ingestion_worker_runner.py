import asyncio
import logging
import time

import redis.asyncio as redis
from openai import AsyncOpenAI
from pinecone import Pinecone
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.observability import (
    classify_provider_failure,
    configure_application_logging,
    initialize_observability,
    lifecycle_event,
    record_ingestion_outcome,
    record_ingestion_prepared,
    record_rag_stage_observation,
    record_worker_heartbeat,
    retrieval_event,
    shutdown_observability,
)
from app.services import (
    contextual_chunking,
    document_parsing,
    document_processor,
    embeddings,
    generations,
    ingestion_worker,
    structured_chunking,
    structured_ingestion,
    tokenization,
)

settings = get_settings()

configure_application_logging(settings.log_level)
logger = logging.getLogger(__name__)
initialize_observability(settings)
pinecone_client = Pinecone(api_key=settings.pinecone_api_key)
openai_client = (
    AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
)


async def _embed_chunks_with_retry(
    chunks,
    *,
    generation_number: int | None = None,
    max_attempts: int = 3,
):
    for attempt in range(1, max_attempts + 1):
        try:
            return await embeddings.embed_chunks(
                provider=settings.embedding_provider,
                chunks=chunks,
                model=settings.embedding_model,
                input_type=settings.embedding_input_type,
                pinecone_client=pinecone_client,
                openai_client=openai_client,
                **(
                    {"generation_number": generation_number}
                    if generation_number is not None
                    else {}
                ),
            )
        except Exception as exc:
            if attempt >= max_attempts:
                lifecycle_event(
                    logger,
                    "embedding_provider_retry_exhausted",
                    level=logging.WARNING,
                    failure_class=classify_provider_failure(exc),
                )
                raise ingestion_worker.RetryableIngestionError(
                    "Embedding provider failed after retries"
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
                lifecycle_event(
                    logger,
                    "vector_upsert_retry_exhausted",
                    level=logging.WARNING,
                    failure_class=classify_provider_failure(exc),
                )
                raise ingestion_worker.RetryableIngestionError(
                    "Vector provider failed after retries"
                ) from exc
            await asyncio.sleep(0.5 * attempt)


async def default_ingestion_processor(
    session: AsyncSession,
    claimed_job: ingestion_worker.ClaimedIngestionJob,
) -> None:
    """Parse document text, chunk it, and persist chunk metadata."""
    if not await ingestion_worker.ensure_claimed_job_processable(
        session, job_id=claimed_job.job.id
    ):
        raise ingestion_worker.NonRetryableIngestionError(
            "Document was deleted or generation became terminal before ingestion"
        )
    metadata = claimed_job.document.metadata_json or {}
    storage_path = metadata.get("storage_path")
    if not isinstance(storage_path, str) or not storage_path:
        raise ingestion_worker.NonRetryableIngestionError(
            "Document storage path is missing"
        )

    generation = getattr(claimed_job, "generation", None)
    is_structured = (
        generation is not None
        and structured_ingestion.uses_structured_generation(
            getattr(generation, "configuration_json", None)
        )
    )
    strategy_version = "legacy_character_v1"
    active_rag_stage = "parsing"
    try:
        if is_structured:
            configuration = generation.configuration_json
            parser = configuration["parser"]
            chunker = configuration["chunker"]
            strategy_version = chunker["strategy"]
            parsing_started = time.perf_counter()
            elements = document_parsing.parse_document(
                storage_path=storage_path,
                mime_type=claimed_job.document.mime_type,
                provider=parser["provider"],
                allow_compatibility_fallback=True,
            )
            record_rag_stage_observation(
                stage="parsing",
                outcome="success",
                duration_ms=(time.perf_counter() - parsing_started) * 1000,
            )
            if not elements:
                raise ingestion_worker.NonRetryableIngestionError(
                    "No extractable text found in document"
                )
            tokenizer = tokenization.get_tokenizer(configuration["tokenizer"]["name"])
            active_rag_stage = "chunking"
            chunking_started = time.perf_counter()
            children = structured_chunking.build_structure_aware_children(
                elements=elements,
                tokenizer=tokenizer,
                document_title=claimed_job.document.filename,
                child_target_tokens=chunker["child_target_tokens"],
                child_max_tokens=chunker["child_max_tokens"],
                child_overlap_tokens=chunker["child_overlap_tokens"],
            )
            children, parents = structured_chunking.build_parent_windows(
                children=children,
                tokenizer=tokenizer,
                parent_target_tokens=chunker["parent_target_tokens"],
                parent_max_tokens=chunker["parent_max_tokens"],
            )
            record_rag_stage_observation(
                stage="chunking",
                outcome="success",
                duration_ms=(time.perf_counter() - chunking_started) * 1000,
            )
            if not children or not parents:
                raise ingestion_worker.NonRetryableIngestionError(
                    "Structured chunk generation produced no output"
                )
            persisted_chunks = (
                await structured_ingestion.persist_parent_child_generation(
                    session,
                    document_id=claimed_job.document.id,
                    generation_id=generation.id,
                    source_file=claimed_job.document.filename,
                    strategy_version=chunker["strategy"],
                    children=children,
                    parents=parents,
                )
            )
            retrieval_event(
                logger,
                "structured_ingestion_prepared",
                generation_id=str(generation.id),
                element_count=len(elements),
                child_count=len(children),
                parent_count=len(parents),
                strategy_version=chunker["strategy"],
            )
            record_ingestion_prepared(
                parser_provider=parser["provider"],
                strategy_version=chunker["strategy"],
                element_count=len(elements),
                child_count=len(children),
                parent_count=len(parents),
                child_token_total=sum(child.token_count for child in children),
                child_overlap_tokens=chunker["child_overlap_tokens"],
            )
            document_text = "\n\n".join(element.text for element in elements)
        else:
            parsing_started = time.perf_counter()
            segments = document_processor.extract_text_segments(
                storage_path=storage_path,
                mime_type=claimed_job.document.mime_type,
            )
            record_rag_stage_observation(
                stage="parsing",
                outcome="success",
                duration_ms=(time.perf_counter() - parsing_started) * 1000,
            )
            if not segments:
                raise ingestion_worker.NonRetryableIngestionError(
                    "No extractable text found in document"
                )
            active_rag_stage = "chunking"
            chunking_started = time.perf_counter()
            chunks = document_processor.build_chunks(
                segments=segments,
                source_file=claimed_job.document.filename,
            )
            record_rag_stage_observation(
                stage="chunking",
                outcome="success",
                duration_ms=(time.perf_counter() - chunking_started) * 1000,
            )
            if not chunks:
                raise ingestion_worker.NonRetryableIngestionError(
                    "Chunk generation produced no output"
                )
            document_text = "\n\n".join(
                segment.text for segment in segments if segment.text.strip()
            )
            if generation is None:
                await document_processor.replace_document_chunks(
                    session, document_id=claimed_job.document.id, chunks=chunks
                )
                persisted_chunks = await document_processor.list_document_chunks(
                    session, document_id=claimed_job.document.id
                )
            else:
                await document_processor.create_generation_chunks(
                    session,
                    document_id=claimed_job.document.id,
                    generation_id=generation.id,
                    chunks=chunks,
                )
                persisted_chunks = await document_processor.list_generation_chunks(
                    session, generation_id=generation.id
                )
    except (
        document_parsing.DocumentParseError,
        tokenization.TokenizerConfigurationError,
        KeyError,
        OSError,
        ValueError,
    ) as exc:
        record_rag_stage_observation(
            stage=active_rag_stage,
            outcome="failure",
            duration_ms=0,
        )
        record_ingestion_outcome(
            outcome="failed",
            strategy_version=strategy_version,
            failure_class="parser",
        )
        raise ingestion_worker.NonRetryableIngestionError(
            "Unable to parse and structure document content"
        ) from exc

    contextualized_lookup: dict[int, str] = {}
    if settings.contextual_embedding_enabled and document_text:
        if settings.contextual_chunking_provider == "openai":
            if openai_client is None or not settings.contextual_chunking_model:
                raise ingestion_worker.NonRetryableIngestionError(
                    "OpenAI contextual chunking is enabled but not configured correctly"
                )
            for chunk in persisted_chunks:
                contextualized_lookup[
                    chunk.chunk_index
                ] = await contextual_chunking.situate_chunk_with_openai(
                    openai_client,
                    document_text=document_text,
                    chunk_text=chunk.chunk_text,
                    model=settings.contextual_chunking_model,
                )
        elif is_structured:
            contextualized_lookup = {
                chunk.chunk_index: document_processor._situate_chunk_with_document_context(
                    document_text=document_text,
                    chunk_text=chunk.chunk_text,
                )
                for chunk in persisted_chunks
            }
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

    # Pinecone metadata is a bounded locator/filter envelope. Source, embedding,
    # lexical, and derived context text remain authoritative only in Postgres.
    for persisted_chunk in persisted_chunks:
        persisted_chunk.metadata_json = {
            "document_id": str(claimed_job.document.id),
            "generation": generation.generation_number if generation else 0,
            "user_id": str(claimed_job.document.user_id),
            "collection_id": (
                str(getattr(claimed_job.document, "collection_id", None))
                if getattr(claimed_job.document, "collection_id", None)
                else ""
            ),
            "chunk_index": getattr(persisted_chunk, "chunk_index", 0),
            "parent_id": str(getattr(persisted_chunk, "parent_id", None) or ""),
            "page_start": getattr(persisted_chunk, "page_start", None) or "",
            "page_end": getattr(persisted_chunk, "page_end", None) or "",
            "source_start": getattr(persisted_chunk, "source_start", None) or "",
            "source_end": getattr(persisted_chunk, "source_end", None) or "",
        }

    chunks_for_embedding = []
    if settings.contextual_embedding_enabled:
        for persisted_chunk in persisted_chunks:
            contextualized_text = contextualized_lookup.get(persisted_chunk.chunk_index)
            if contextualized_text:
                # Contextualization is model-generated retrieval aid, never source
                # evidence. Keep it independently versioned so citations and
                # grounded prompts continue to hydrate immutable `chunk_text`.
                persisted_chunk.derived_context_text = contextualized_text
                persisted_chunk.derived_context_version = (
                    f"{settings.contextual_chunking_provider}:"
                    f"{settings.contextual_chunking_model or 'native'}"
                )
            chunks_for_embedding.append(persisted_chunk)
    else:
        chunks_for_embedding = persisted_chunks

    if generation is None:
        embedded_chunks = await _embed_chunks_with_retry(chunks_for_embedding)
    else:
        embedded_chunks = await _embed_chunks_with_retry(
            chunks_for_embedding,
            generation_number=generation.generation_number,
        )

    namespace = embeddings.build_pinecone_namespace(
        user_id=claimed_job.document.user_id
    )
    if not await ingestion_worker.ensure_claimed_job_processable(
        session, job_id=claimed_job.job.id
    ):
        raise ingestion_worker.NonRetryableIngestionError(
            "Document was deleted or generation became terminal before vector upsert"
        )
    await _upsert_embeddings_with_retry(
        namespace=namespace,
        embedded_chunks=embedded_chunks,
    )

    embedded_lookup = {item.chunk_id: item.vector_id for item in embedded_chunks}
    for chunk_row in persisted_chunks:
        chunk_row.vector_id = embedded_lookup.get(chunk_row.id)

    if generation is not None:
        activated = await generations.activate_generation(
            session,
            document_id=claimed_job.document.id,
            generation_id=generation.id,
            vector_ids=[item.vector_id for item in embedded_chunks],
            job_id=claimed_job.job.id,
        )
        if not activated:
            record_ingestion_outcome(
                outcome="failed",
                strategy_version=strategy_version,
                failure_class="activation",
            )
            raise ingestion_worker.NonRetryableIngestionError(
                "Generation activation fenced by document lifecycle"
            )

    record_ingestion_outcome(
        outcome="ready",
        strategy_version=strategy_version,
    )

    lifecycle_event(
        logger,
        "processing_ingestion_job",
        attempts=claimed_job.job.attempts,
        count=len(persisted_chunks),
        outcome="ready",
    )


async def run_worker_loop() -> None:
    redis_client = redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=10,
        # The socket timeout must outlast the intentionally blocking BLPOP.
        socket_timeout=settings.ingestion_worker_dequeue_timeout_seconds + 5,
        health_check_interval=30,
    )
    try:
        await redis_client.ping()
    except RedisError as exc:
        lifecycle_event(
            logger,
            "ingestion_queue_startup_unavailable_using_database_fallback",
            level=logging.WARNING,
            outcome="database_fallback",
            failure_class="redis",
            error_type=type(exc).__name__,
        )

    lifecycle_event(
        logger,
        "ingestion_worker_started",
        dequeue_timeout_seconds=settings.ingestion_worker_dequeue_timeout_seconds,
        max_attempts=settings.ingestion_worker_max_attempts,
        outcome="started",
    )

    try:
        while True:
            record_worker_heartbeat(worker="ingestion")
            async with AsyncSessionLocal() as session:
                recovered = await ingestion_worker.recover_stuck_ingestion_jobs(
                    session,
                    stuck_timeout_seconds=settings.ingestion_worker_stuck_timeout_seconds,
                    max_attempts=settings.ingestion_worker_max_attempts,
                    retry_base_seconds=settings.ingestion_retry_base_seconds,
                    retry_max_seconds=settings.ingestion_retry_max_seconds,
                )
                if recovered:
                    lifecycle_event(
                        logger,
                        "ingestion_worker_recovered_stuck_jobs",
                        level=logging.WARNING,
                        count=recovered,
                        outcome="recovered",
                    )
                processed = await ingestion_worker.process_next_ingestion_job(
                    session,
                    redis_client=redis_client,
                    queue_key=settings.ingestion_queue_key,
                    dequeue_timeout_seconds=settings.ingestion_worker_dequeue_timeout_seconds,
                    max_attempts=settings.ingestion_worker_max_attempts,
                    retry_base_seconds=settings.ingestion_retry_base_seconds,
                    retry_max_seconds=settings.ingestion_retry_max_seconds,
                    processor=default_ingestion_processor,
                )

            if not processed:
                await asyncio.sleep(settings.ingestion_worker_idle_sleep_seconds)
    finally:
        try:
            await redis_client.aclose()
        except RedisError as exc:
            lifecycle_event(
                logger,
                "ingestion_queue_close_failed",
                level=logging.DEBUG,
                outcome="ignored",
                failure_class="redis",
                error_type=type(exc).__name__,
            )


def main() -> None:
    try:
        asyncio.run(run_worker_loop())
    finally:
        shutdown_observability()


if __name__ == "__main__":
    main()
