import os
import types
import uuid

import pytest

# This module can be collected before router tests, which otherwise establish the
# test environment before importing services that read cached settings.
os.environ.setdefault("ENVIRONMENT", "test")

from app.models.entities import (
    DocumentLifecycleStatus,
    GenerationStatus,
    IngestionStatus,
)
from app.services import documents


class _DuplicateSession:
    def __init__(self, document, failed_job) -> None:
        self._scalar_values = [document, None, failed_job, 1]
        self.added: list[object] = []
        self.commits = 0
        self.deleted = False

    async def scalar(self, _statement):
        return self._scalar_values.pop(0)

    def add(self, item) -> None:
        self.added.append(item)
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _item) -> None:
        return None

    async def delete(self, _item) -> None:
        self.deleted = True


class _DocumentReadSession:
    def __init__(self, document, job) -> None:
        self.document = document
        self.job = job
        self.statements = []

    async def scalar(self, _statement):
        return 1

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return types.SimpleNamespace(all=lambda: [(self.document, 0)])
        return types.SimpleNamespace(all=lambda: [(self.job, 4)])


@pytest.mark.asyncio
async def test_duplicate_after_failed_ingestion_retains_document_and_queues_generation() -> (
    None
):
    user_id = uuid.uuid4()
    document = types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id,
        file_hash="hash",
        lifecycle_status=DocumentLifecycleStatus.active,
        active_generation_id=None,
        status=IngestionStatus.failed,
    )
    failed_job = types.SimpleNamespace(
        id=uuid.uuid4(),
        status=IngestionStatus.failed,
    )
    session = _DuplicateSession(document, failed_job)

    result = await documents.create_uploaded_document(
        session,  # type: ignore[arg-type]
        user_id=user_id,
        filename="notes.txt",
        mime_type="text/plain",
        file_bytes=b"same content",
        collection_id=None,
    )

    generation = next(
        item
        for item in session.added
        if item.__class__.__name__ == "DocumentIngestionGeneration"
    )
    job = next(
        item for item in session.added if item.__class__.__name__ == "IngestionJob"
    )
    assert session.deleted is False
    assert result.document is document
    assert result.job is job
    assert result.deduplicated is True
    assert result.enqueue_job is True
    assert generation.status == GenerationStatus.pending
    assert job.generation_id == generation.id
    assert document.status == IngestionStatus.queued


@pytest.mark.asyncio
async def test_document_list_scopes_read_model_to_requesting_user_before_loading_jobs() -> (
    None
):
    user_id = uuid.uuid4()
    document = types.SimpleNamespace(id=uuid.uuid4())
    job = types.SimpleNamespace(document_id=document.id)
    session = _DocumentReadSession(document, job)

    result, total = await documents.list_documents(
        session,  # type: ignore[arg-type]
        user_id=user_id,
        collection_id=None,
        limit=50,
        offset=0,
    )

    compiled = session.statements[0].compile()
    assert user_id in compiled.params.values()
    assert "documents.user_id" in str(session.statements[0])
    assert total == 1
    assert result[0].latest_job is not None
    assert result[0].latest_job.generation_number == 4
