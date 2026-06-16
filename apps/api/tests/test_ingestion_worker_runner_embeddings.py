import types
import uuid

import pytest

from app.services import ingestion_worker_runner


@pytest.mark.asyncio
async def test_embed_chunks_with_retry_succeeds_after_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    async def _fake_embed(
        *,
        provider,
        chunks,
        model,
        input_type,
        pinecone_client,
        openai_client,
    ):
        _ = provider, chunks, model, input_type, pinecone_client, openai_client
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("temporary embed failure")
        return ["ok"]

    monkeypatch.setattr(ingestion_worker_runner.embeddings, "embed_chunks", _fake_embed)

    result = await ingestion_worker_runner._embed_chunks_with_retry([object()])

    assert result == ["ok"]
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_upsert_embeddings_with_retry_succeeds_after_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def _fake_upsert(_client, *, index_name, namespace, embedded_chunks):
        _ = index_name, namespace, embedded_chunks
        calls["count"] += 1
        if calls["count"] < 2:
            raise RuntimeError("temporary upsert failure")

    monkeypatch.setattr(
        ingestion_worker_runner.embeddings,
        "upsert_embeddings",
        _fake_upsert,
    )

    await ingestion_worker_runner._upsert_embeddings_with_retry(
        namespace="user:test",
        embedded_chunks=[object()],
    )

    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_default_ingestion_processor_sets_vector_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid.uuid4()
    user_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    claimed = types.SimpleNamespace(
        job=types.SimpleNamespace(id=uuid.uuid4(), attempts=1),
        document=types.SimpleNamespace(
            id=document_id,
            user_id=user_id,
            filename="notes.txt",
            mime_type="text/plain",
            metadata_json={"storage_path": "/tmp/notes.txt"},
        ),
    )

    chunk_row = types.SimpleNamespace(id=chunk_id, vector_id=None)

    monkeypatch.setattr(
        ingestion_worker_runner.document_processor,
        "extract_text_segments",
        lambda **_kwargs: [types.SimpleNamespace(page_number=1, text="hello world")],
    )
    monkeypatch.setattr(
        ingestion_worker_runner.document_processor,
        "build_chunks",
        lambda **_kwargs: [
            types.SimpleNamespace(
                chunk_index=0,
                chunk_text="hello world",
                token_count=2,
                metadata={"source_file": "notes.txt"},
            )
        ],
    )

    async def _fake_replace(_session, *, document_id, chunks):
        _ = document_id, chunks
        return 1

    async def _fake_list(_session, *, document_id):
        _ = document_id
        return [chunk_row]

    async def _fake_embed(_chunks):
        _ = _chunks
        return [types.SimpleNamespace(chunk_id=chunk_id, vector_id=f"chunk:{chunk_id}")]

    async def _fake_upsert(*, namespace, embedded_chunks):
        assert namespace == f"user:{user_id}"
        assert len(embedded_chunks) == 1

    monkeypatch.setattr(
        ingestion_worker_runner.document_processor,
        "replace_document_chunks",
        _fake_replace,
    )
    monkeypatch.setattr(
        ingestion_worker_runner.document_processor,
        "list_document_chunks",
        _fake_list,
    )
    monkeypatch.setattr(
        ingestion_worker_runner, "_embed_chunks_with_retry", _fake_embed
    )
    monkeypatch.setattr(
        ingestion_worker_runner,
        "_upsert_embeddings_with_retry",
        _fake_upsert,
    )

    await ingestion_worker_runner.default_ingestion_processor(object(), claimed)

    assert chunk_row.vector_id == f"chunk:{chunk_id}"
