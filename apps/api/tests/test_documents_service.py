import types
import uuid

import pytest

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
