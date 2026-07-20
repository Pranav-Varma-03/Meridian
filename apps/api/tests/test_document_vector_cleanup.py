import types
import uuid

import pytest

from app.models.entities import DocumentLifecycleStatus, PurgeJobStatus
from app.services import documents


class _ScalarValues:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def all(self) -> list[str]:
        return self._values


class _Session:
    def __init__(self, document):
        self.document = document
        self.added = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.document

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _value):
        return None


@pytest.mark.asyncio
async def test_document_delete_is_logical_and_enqueues_durable_purge() -> None:
    user_id = uuid.uuid4()
    document = types.SimpleNamespace(
        id=uuid.uuid4(), lifecycle_status=DocumentLifecycleStatus.active
    )
    session = _Session(document)

    job = await documents.delete_document(
        session,  # type: ignore[arg-type]
        user_id=user_id,
        document_id=document.id,
    )

    assert document.lifecycle_status == DocumentLifecycleStatus.deleting
    assert job.status == PurgeJobStatus.queued
    assert len(session.added) == 2
    assert session.commits == 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_document_not_found_does_not_enqueue_purge() -> None:
    session = _Session(document=None)
    with pytest.raises(documents.DocumentNotFoundError):
        await documents.delete_document(
            session,  # type: ignore[arg-type]
            user_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
        )

    assert session.added == []
