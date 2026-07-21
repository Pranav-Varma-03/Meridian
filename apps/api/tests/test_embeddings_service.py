import types
import uuid

import pytest

from app.services import embeddings


class _DummyChunk:
    def __init__(self, *, idx: int) -> None:
        self.id = uuid.uuid4()
        self.document_id = uuid.uuid4()
        self.chunk_index = idx
        self.chunk_text = f"chunk-{idx}"
        self.metadata_json = {
            "source_file": "notes.txt",
            "page_number": idx + 1,
            "section_heading": None,
        }


class _DummyPineconeForEmbed:
    class _Inference:
        def embed(self, *, model, inputs, parameters=None):
            _ = model
            assert parameters == {"input_type": "passage"}
            return types.SimpleNamespace(
                data=[
                    types.SimpleNamespace(values=[float(i), float(i + 1)])
                    for i, _ in enumerate(inputs)
                ]
            )

    def __init__(self) -> None:
        self.inference = self._Inference()


class _DummyOpenAI:
    class _Embeddings:
        async def create(self, *, model, input):
            _ = model
            return types.SimpleNamespace(
                data=[
                    types.SimpleNamespace(embedding=[float(i), float(i + 1)])
                    for i, _ in enumerate(input)
                ]
            )

    def __init__(self) -> None:
        self.embeddings = self._Embeddings()


class _DummyPineconeIndex:
    def __init__(self) -> None:
        self.upserts = []
        self.deletes = []

    def upsert(self, *, vectors, namespace):
        self.upserts.append({"vectors": vectors, "namespace": namespace})

    def delete(self, *, ids, namespace):
        self.deletes.append({"ids": ids, "namespace": namespace})


class _DummyPinecone:
    def __init__(self) -> None:
        self.index = _DummyPineconeIndex()

    def Index(self, _index_name):  # noqa: N802
        return self.index


def test_build_pinecone_namespace() -> None:
    user_id = uuid.uuid4()
    assert embeddings.build_pinecone_namespace(user_id=user_id) == f"user:{user_id}"


@pytest.mark.asyncio
async def test_embed_chunks_returns_vector_payloads() -> None:
    chunks = [_DummyChunk(idx=0), _DummyChunk(idx=1)]

    embedded = await embeddings.embed_chunks(
        provider="pinecone",
        pinecone_client=_DummyPineconeForEmbed(),  # type: ignore[arg-type]
        chunks=chunks,  # type: ignore[arg-type]
        model="llama-text-embed-v2",
        input_type="passage",
    )

    assert len(embedded) == 2
    assert embedded[0].vector_id == f"chunk:{chunks[0].id}"
    assert embedded[0].metadata["document_id"] == str(chunks[0].document_id)
    assert embedded[0].metadata["section_heading"] == ""


@pytest.mark.asyncio
async def test_embed_chunks_supports_openai_provider() -> None:
    chunks = [_DummyChunk(idx=0)]

    embedded = await embeddings.embed_chunks(
        provider="openai",
        openai_client=_DummyOpenAI(),  # type: ignore[arg-type]
        chunks=chunks,  # type: ignore[arg-type]
        model="text-embedding-3-small",
    )

    assert len(embedded) == 1
    assert embedded[0].vector_id == f"chunk:{chunks[0].id}"


def test_upsert_embeddings_calls_pinecone_index_upsert() -> None:
    dummy_pinecone = _DummyPinecone()
    chunk_id = uuid.uuid4()
    payload = [
        embeddings.EmbeddedChunk(
            chunk_id=chunk_id,
            vector_id=f"chunk:{chunk_id}",
            values=[0.1, 0.2],
            metadata={"chunk_id": str(chunk_id)},
        )
    ]

    embeddings.upsert_embeddings(
        dummy_pinecone,  # type: ignore[arg-type]
        index_name="test-index",
        namespace="user:test",
        embedded_chunks=payload,
    )

    assert len(dummy_pinecone.index.upserts) == 1
    upsert_call = dummy_pinecone.index.upserts[0]
    assert upsert_call["namespace"] == "user:test"
    assert upsert_call["vectors"][0]["id"] == f"chunk:{chunk_id}"


@pytest.mark.asyncio
async def test_delete_embeddings_batches_ids_and_preserves_namespace() -> None:
    dummy_pinecone = _DummyPinecone()

    await embeddings.delete_embeddings(
        dummy_pinecone,  # type: ignore[arg-type]
        index_name="test-index",
        namespace="user:test",
        vector_ids=["one", "two", "one", "three"],
        batch_size=2,
        timeout_seconds=1,
        max_attempts=1,
    )

    assert dummy_pinecone.index.deletes == [
        {"ids": ["one", "two"], "namespace": "user:test"},
        {"ids": ["three"], "namespace": "user:test"},
    ]


@pytest.mark.asyncio
async def test_delete_embeddings_empty_ids_skips_pinecone() -> None:
    dummy_pinecone = _DummyPinecone()

    await embeddings.delete_embeddings(
        dummy_pinecone,  # type: ignore[arg-type]
        index_name="test-index",
        namespace="user:test",
        vector_ids=[],
        batch_size=2,
        timeout_seconds=1,
        max_attempts=1,
    )

    assert dummy_pinecone.index.deletes == []


@pytest.mark.asyncio
async def test_delete_embeddings_exposes_retryable_failure() -> None:
    class _UnavailableIndex:
        def delete(self, *, ids, namespace):
            _ = (ids, namespace)
            raise ConnectionError("Pinecone unavailable")

    class _UnavailablePinecone:
        def Index(self, _index_name):  # noqa: N802
            return _UnavailableIndex()

    with pytest.raises(embeddings.VectorDeletionError) as error:
        await embeddings.delete_embeddings(
            _UnavailablePinecone(),  # type: ignore[arg-type]
            index_name="test-index",
            namespace="user:test",
            vector_ids=["one"],
            batch_size=1,
            timeout_seconds=1,
            max_attempts=1,
        )

    assert error.value.retryable is True


@pytest.mark.asyncio
async def test_delete_embeddings_by_metadata_filter_uses_owner_scope() -> None:
    class FilterIndex:
        def __init__(self) -> None:
            self.calls = []

        def delete(self, **kwargs) -> None:
            self.calls.append(kwargs)

    class FilterClient:
        def __init__(self) -> None:
            self.index = FilterIndex()

        def Index(self, _name):  # noqa: N802
            return self.index

    client = FilterClient()
    await embeddings.delete_embeddings_by_metadata_filter(
        client,  # type: ignore[arg-type]
        index_name="test-index",
        namespace="user:owner",
        metadata_filter={"document_id": "document-1", "generation": 2},
        timeout_seconds=1,
        max_attempts=1,
    )

    assert client.index.calls == [
        {
            "filter": {
                "document_id": {"$eq": "document-1"},
                "generation": {"$eq": 2},
            },
            "namespace": "user:owner",
        }
    ]
