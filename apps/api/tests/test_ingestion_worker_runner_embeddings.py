import types
import uuid

import pytest

from app.services import ingestion_worker_runner
from app.services.document_parsing import DocumentElement, DocumentParseError


@pytest.fixture(autouse=True)
def _allow_test_processor_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests here isolate embedding behavior from DB lifecycle fencing."""

    async def _processable(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr(
        ingestion_worker_runner.ingestion_worker,
        "ensure_claimed_job_processable",
        _processable,
    )


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


@pytest.mark.asyncio
async def test_default_ingestion_processor_uses_structured_generation_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid.uuid4()
    user_id = uuid.uuid4()
    generation_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    configuration = {
        "parser": {"provider": "compatibility"},
        "tokenizer": {"name": "cl100k_base"},
        "chunker": {
            "strategy": "structure_aware_parent_child_v1",
            "child_target_tokens": 384,
            "child_max_tokens": 512,
            "child_overlap_tokens": 48,
            "parent_target_tokens": 900,
            "parent_max_tokens": 1200,
        },
    }
    claimed = types.SimpleNamespace(
        job=types.SimpleNamespace(id=uuid.uuid4(), attempts=1),
        document=types.SimpleNamespace(
            id=document_id,
            user_id=user_id,
            filename="policy.txt",
            mime_type="text/plain",
            metadata_json={"storage_path": "/tmp/policy.txt"},
            collection_id=None,
        ),
        generation=types.SimpleNamespace(
            id=generation_id,
            generation_number=2,
            configuration_json=configuration,
        ),
    )
    row = types.SimpleNamespace(
        id=chunk_id,
        chunk_index=0,
        chunk_text="exact policy evidence",
        embedding_text="Document: policy.txt\n\nexact policy evidence",
        parent_id=uuid.uuid4(),
        page_start=1,
        page_end=1,
        source_start=0,
        source_end=21,
        vector_id=None,
        metadata_json={},
    )
    captured = {}

    monkeypatch.setattr(
        ingestion_worker_runner.document_parsing,
        "parse_document",
        lambda **_kwargs: [
            DocumentElement(
                element_type="paragraph",
                text="exact policy evidence",
                section_path=(),
                page_start=1,
                page_end=1,
                source_start=0,
                source_end=21,
            )
        ],
    )

    async def _persist(_session, **kwargs):
        captured["persist"] = kwargs
        return [row]

    async def _embed(chunks, *, generation_number=None):
        captured["embedded_text"] = chunks[0].embedding_text
        captured["generation_number"] = generation_number
        return [types.SimpleNamespace(chunk_id=chunk_id, vector_id="vector-1")]

    async def _upsert(*, namespace, embedded_chunks):
        captured["namespace"] = namespace
        assert embedded_chunks[0].vector_id == "vector-1"

    async def _activate(_session, **kwargs):
        captured["activation"] = kwargs
        return True

    monkeypatch.setattr(
        ingestion_worker_runner.structured_ingestion,
        "persist_parent_child_generation",
        _persist,
    )
    monkeypatch.setattr(ingestion_worker_runner, "_embed_chunks_with_retry", _embed)
    monkeypatch.setattr(
        ingestion_worker_runner, "_upsert_embeddings_with_retry", _upsert
    )
    monkeypatch.setattr(
        ingestion_worker_runner.generations, "activate_generation", _activate
    )
    monkeypatch.setattr(
        ingestion_worker_runner.settings, "contextual_embedding_enabled", False
    )

    await ingestion_worker_runner.default_ingestion_processor(object(), claimed)

    assert captured["persist"]["generation_id"] == generation_id
    assert captured["embedded_text"].startswith("Document: policy.txt")
    assert captured["generation_number"] == 2
    assert captured["activation"]["vector_ids"] == ["vector-1"]
    assert row.chunk_text == "exact policy evidence"
    assert "chunk_text" not in row.metadata_json


@pytest.mark.asyncio
async def test_structured_ingestion_parser_failure_is_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claimed = types.SimpleNamespace(
        job=types.SimpleNamespace(id=uuid.uuid4(), attempts=1),
        document=types.SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            filename="scan.pdf",
            mime_type="application/pdf",
            metadata_json={"storage_path": "/tmp/scan.pdf"},
        ),
        generation=types.SimpleNamespace(
            id=uuid.uuid4(),
            generation_number=1,
            configuration_json={
                "parser": {"provider": "unstructured"},
                "tokenizer": {"name": "cl100k_base"},
                "chunker": {"strategy": "structure_aware_parent_child_v1"},
            },
        ),
    )

    def _parse_failure(**_kwargs):
        raise DocumentParseError("OCR is unsupported")

    monkeypatch.setattr(
        ingestion_worker_runner.document_parsing, "parse_document", _parse_failure
    )

    with pytest.raises(
        ingestion_worker_runner.ingestion_worker.NonRetryableIngestionError,
        match="Unable to parse",
    ):
        await ingestion_worker_runner.default_ingestion_processor(object(), claimed)


@pytest.mark.asyncio
async def test_default_ingestion_processor_uses_openai_contextual_chunking_when_enabled(
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

    chunk_row = types.SimpleNamespace(
        id=chunk_id,
        chunk_index=0,
        chunk_text="plain text",
        vector_id=None,
        embedding_text=None,
        derived_context_text=None,
        derived_context_version=None,
    )

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
                chunk_text="plain text",
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

    async def _fake_contextualize(_client, *, document_text, chunk_text, model):
        _ = document_text, chunk_text, model
        return "llm contextualized chunk text"

    captured_chunks = {}

    async def _fake_embed(_chunks):
        captured_chunks["source_text"] = _chunks[0].chunk_text
        captured_chunks["derived_context"] = _chunks[0].derived_context_text
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
        ingestion_worker_runner.contextual_chunking,
        "situate_chunk_with_openai",
        _fake_contextualize,
    )
    monkeypatch.setattr(
        ingestion_worker_runner.settings,
        "contextual_embedding_enabled",
        True,
    )
    monkeypatch.setattr(
        ingestion_worker_runner.settings,
        "contextual_chunking_provider",
        "openai",
    )
    monkeypatch.setattr(
        ingestion_worker_runner.settings,
        "contextual_chunking_model",
        "gpt-4o-mini",
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

    assert captured_chunks == {
        "source_text": "plain text",
        "derived_context": "llm contextualized chunk text",
    }
    assert chunk_row.derived_context_version == "openai:gpt-4o-mini"
    assert chunk_row.vector_id == f"chunk:{chunk_id}"


@pytest.mark.asyncio
async def test_default_ingestion_processor_uses_contextual_chunks_when_enabled(
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

    chunk_row = types.SimpleNamespace(
        id=chunk_id,
        chunk_index=0,
        chunk_text="plain text",
        vector_id=None,
        embedding_text=None,
        derived_context_text=None,
        derived_context_version=None,
    )

    monkeypatch.setattr(
        ingestion_worker_runner.document_processor,
        "extract_text_segments",
        lambda **_kwargs: [types.SimpleNamespace(page_number=1, text="hello world")],
    )
    monkeypatch.setattr(
        ingestion_worker_runner.document_processor,
        "build_contextualized_chunks",
        lambda **_kwargs: [
            types.SimpleNamespace(
                chunk_index=0,
                chunk_text="plain text",
                contextualized_text="contextualized chunk text",
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

    captured_chunks = {}

    async def _fake_embed(_chunks):
        captured_chunks["source_text"] = _chunks[0].chunk_text
        captured_chunks["derived_context"] = _chunks[0].derived_context_text
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
        ingestion_worker_runner.settings,
        "contextual_embedding_enabled",
        True,
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

    assert captured_chunks == {
        "source_text": "plain text",
        "derived_context": "contextualized chunk text",
    }
    assert chunk_row.derived_context_version == "native:native"
    assert chunk_row.vector_id == f"chunk:{chunk_id}"
