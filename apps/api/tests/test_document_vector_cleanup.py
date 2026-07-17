import types
import uuid

import pytest

from app.services import documents, embeddings


class _ScalarValues:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def all(self) -> list[str]:
        return self._values


class _Session:
    def __init__(self, document):
        self.document = document
        self.deleted = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.document

    async def scalars(self, _statement):
        return _ScalarValues(["chunk:one", "chunk:two"])

    async def delete(self, document):
        self.deleted.append(document)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_document_cleanup_deletes_owned_vectors_before_database_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid.uuid4()
    document = types.SimpleNamespace(id=uuid.uuid4())
    session = _Session(document)
    captured = {}

    async def _delete_embeddings(_client, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(embeddings, "delete_embeddings", _delete_embeddings)

    await documents.delete_document(
        session,  # type: ignore[arg-type]
        user_id=user_id,
        document_id=document.id,
        pinecone_client=object(),
        pinecone_index_name="test-index",
        vector_delete_batch_size=100,
        vector_delete_timeout_seconds=1,
        vector_delete_max_attempts=1,
        request_id="request-123",
    )

    assert captured["namespace"] == f"user:{user_id}"
    assert captured["vector_ids"] == ["chunk:one", "chunk:two"]
    assert session.deleted == [document]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_document_cleanup_failure_keeps_document_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = types.SimpleNamespace(id=uuid.uuid4())
    session = _Session(document)

    async def _delete_embeddings(_client, **_kwargs):
        raise embeddings.VectorDeletionError(retryable=True)

    monkeypatch.setattr(embeddings, "delete_embeddings", _delete_embeddings)

    with pytest.raises(documents.VectorCleanupUnavailableError):
        await documents.delete_document(
            session,  # type: ignore[arg-type]
            user_id=uuid.uuid4(),
            document_id=document.id,
            pinecone_client=object(),
            pinecone_index_name="test-index",
            vector_delete_batch_size=100,
            vector_delete_timeout_seconds=1,
            vector_delete_max_attempts=1,
            request_id="request-123",
        )

    assert session.deleted == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_document_not_found_does_not_invoke_vector_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session(document=None)
    called = False

    async def _delete_embeddings(_client, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(embeddings, "delete_embeddings", _delete_embeddings)

    with pytest.raises(documents.DocumentNotFoundError):
        await documents.delete_document(
            session,  # type: ignore[arg-type]
            user_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            pinecone_client=object(),
            pinecone_index_name="test-index",
            vector_delete_batch_size=100,
            vector_delete_timeout_seconds=1,
            vector_delete_max_attempts=1,
            request_id="request-123",
        )

    assert called is False
