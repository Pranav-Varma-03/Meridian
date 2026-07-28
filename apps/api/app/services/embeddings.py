import asyncio
import uuid
from dataclasses import dataclass

from openai import AsyncOpenAI
from pinecone import Pinecone

from app.models.entities import DocumentChunk


@dataclass(slots=True)
class EmbeddedChunk:
    chunk_id: uuid.UUID
    vector_id: str
    values: list[float]
    metadata: dict


class VectorDeletionError(Exception):
    """Raised when Pinecone vector cleanup cannot complete safely."""

    def __init__(self, *, retryable: bool) -> None:
        super().__init__("Vector cleanup failed")
        self.retryable = retryable


def _normalize_metadata(metadata: dict | None) -> dict[str, str | int | float | bool]:
    normalized: dict[str, str | int | float | bool] = {}
    if not metadata:
        return normalized

    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            normalized[str(key)] = value
        elif value is None:
            normalized[str(key)] = ""
        else:
            normalized[str(key)] = str(value)
    return normalized


def build_pinecone_namespace(*, user_id: uuid.UUID) -> str:
    return f"user:{user_id}"


async def embed_chunks(
    *,
    provider: str,
    model: str,
    input_type: str | None = None,
    chunks: list[DocumentChunk],
    pinecone_client: Pinecone | None = None,
    openai_client: AsyncOpenAI | None = None,
    generation_number: int | None = None,
) -> list[EmbeddedChunk]:
    if not chunks:
        return []

    response_items: list = []
    if provider == "pinecone":
        if pinecone_client is None:
            raise ValueError(
                "Pinecone client is required for pinecone embedding provider"
            )

        inputs = [{"text": chunk.chunk_text} for chunk in chunks]
        embed_kwargs: dict[str, object] = {
            "model": model,
            "inputs": inputs,
        }
        if input_type:
            embed_kwargs["parameters"] = {"input_type": input_type}

        response = pinecone_client.inference.embed(**embed_kwargs)
        response_items = getattr(response, "data", None) or []
        if not response_items and isinstance(response, dict):
            response_items = response.get("data", [])
    elif provider == "openai":
        if openai_client is None:
            raise ValueError("OpenAI client is required for openai embedding provider")

        inputs = [chunk.chunk_text for chunk in chunks]
        response = await openai_client.embeddings.create(model=model, input=inputs)
        response_items = list(response.data)
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")

    if len(response_items) != len(chunks):
        raise ValueError("Embedding response item count does not match chunk count")

    embedded: list[EmbeddedChunk] = []
    for chunk, item in zip(chunks, response_items, strict=True):
        if isinstance(item, dict):
            values = item.get("values", [])
        else:
            values = getattr(item, "values", None)
            if values is None:
                values = getattr(item, "embedding", [])
        vector_id = (
            f"doc:{chunk.document_id}:gen:{generation_number}:chunk:{chunk.chunk_index}"
            if generation_number is not None
            else f"chunk:{chunk.id}"
        )
        metadata = _normalize_metadata(chunk.metadata_json)
        metadata.update(
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "chunk_index": chunk.chunk_index,
                "generation": generation_number if generation_number is not None else 0,
            }
        )
        embedded.append(
            EmbeddedChunk(
                chunk_id=chunk.id,
                vector_id=vector_id,
                values=list(values),
                metadata=metadata,
            )
        )
    return embedded


async def embed_query(
    *,
    provider: str,
    model: str,
    query: str,
    pinecone_client: Pinecone | None = None,
    openai_client: AsyncOpenAI | None = None,
) -> list[float]:
    """Embed one user query using the provider's retrieval-query mode."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("Query must not be empty")

    if provider == "pinecone":
        if pinecone_client is None:
            raise ValueError("Pinecone client is required for pinecone embeddings")
        response = pinecone_client.inference.embed(
            model=model,
            inputs=[{"text": normalized_query}],
            parameters={"input_type": "query"},
        )
        items = getattr(response, "data", None) or (
            response.get("data", []) if isinstance(response, dict) else []
        )
        if len(items) != 1:
            raise ValueError("Query embedding response must contain one vector")
        item = items[0]
        values = (
            item.get("values", [])
            if isinstance(item, dict)
            else getattr(item, "values", [])
        )
        return list(values)

    if provider == "openai":
        if openai_client is None:
            raise ValueError("OpenAI client is required for openai embeddings")
        response = await openai_client.embeddings.create(
            model=model, input=normalized_query
        )
        if len(response.data) != 1:
            raise ValueError("Query embedding response must contain one vector")
        return list(response.data[0].embedding)

    raise ValueError(f"Unsupported embedding provider: {provider}")


def upsert_embeddings(
    pinecone_client: Pinecone,
    *,
    index_name: str,
    namespace: str,
    embedded_chunks: list[EmbeddedChunk],
) -> None:
    if not embedded_chunks:
        return

    index = pinecone_client.Index(index_name)
    vectors = [
        {
            "id": item.vector_id,
            "values": item.values,
            "metadata": item.metadata,
        }
        for item in embedded_chunks
    ]
    index.upsert(vectors=vectors, namespace=namespace)


def _is_retryable_vector_error(exc: Exception) -> bool:
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500

    return isinstance(exc, (ConnectionError, TimeoutError)) or any(
        marker in exc.__class__.__name__.lower()
        for marker in ("timeout", "connection", "unavailable", "temporar")
    )


async def delete_embeddings(
    pinecone_client: Pinecone,
    *,
    index_name: str,
    namespace: str,
    vector_ids: list[str],
    batch_size: int,
    timeout_seconds: float,
    max_attempts: int,
) -> None:
    """Delete exact vector IDs from one namespace with bounded retries.

    Deleting an ID that is already absent is a successful, idempotent operation in
    Pinecone. This function intentionally accepts only a server-derived namespace.
    """
    unique_vector_ids = list(dict.fromkeys(vector_ids))
    if not unique_vector_ids:
        return

    index = pinecone_client.Index(index_name)
    for start in range(0, len(unique_vector_ids), batch_size):
        batch = unique_vector_ids[start : start + batch_size]
        for attempt in range(1, max_attempts + 1):
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(index.delete, ids=batch, namespace=namespace),
                    timeout=timeout_seconds,
                )
                break
            except Exception as exc:
                retryable = _is_retryable_vector_error(exc)
                if not retryable or attempt == max_attempts:
                    raise VectorDeletionError(retryable=retryable) from exc
                await asyncio.sleep(0.1 * attempt)


async def delete_embeddings_by_metadata_filter(
    pinecone_client: Pinecone,
    *,
    index_name: str,
    namespace: str,
    metadata_filter: dict[str, str | int | float | bool],
    timeout_seconds: float,
    max_attempts: int,
) -> None:
    """Reconcile vectors using server-derived metadata after exact-ID deletion.

    This is intentionally separate from ``delete_embeddings``: callers must make
    an explicit decision about the scope of the metadata filter. A superseded
    generation must include both document and generation; a document-wide filter
    is only safe after the document has been logically hidden.
    """
    # Pinecone metadata filtering uses comparison operators. Normalising scalar
    # caller values here keeps purge scope explicit and prevents an adapter caller
    # from accidentally relying on SDK-specific implicit equality behaviour.
    supported_filter = {key: {"$eq": value} for key, value in metadata_filter.items()}
    index = pinecone_client.Index(index_name)
    for attempt in range(1, max_attempts + 1):
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    index.delete,
                    filter=supported_filter,
                    namespace=namespace,
                ),
                timeout=timeout_seconds,
            )
            return
        except Exception as exc:
            retryable = _is_retryable_vector_error(exc)
            if not retryable or attempt == max_attempts:
                raise VectorDeletionError(retryable=retryable) from exc
            await asyncio.sleep(0.1 * attempt)
