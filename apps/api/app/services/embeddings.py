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
        vector_id = f"chunk:{chunk.id}"
        metadata = _normalize_metadata(chunk.metadata_json)
        metadata.update(
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "chunk_index": chunk.chunk_index,
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
