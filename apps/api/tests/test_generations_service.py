import types
import uuid

import pytest

from app.models.entities import (
    DocumentLifecycleStatus,
    GenerationStatus,
    IngestionStatus,
    PurgeJobStatus,
)
from app.services import generations


class _Session:
    def __init__(self, document, generation, previous):
        self.values = [document, generation, previous]
        self.added = []
        self.commits = 0

    async def scalar(self, _statement):
        return self.values.pop(0)

    def add(self, item):
        self.added.append(item)
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_activate_generation_switches_pointer_and_queues_previous_purge() -> None:
    document_id = uuid.uuid4()
    previous_id = uuid.uuid4()
    generation_id = uuid.uuid4()
    document = types.SimpleNamespace(
        id=document_id,
        active_generation_id=previous_id,
        status=IngestionStatus.processing,
        lifecycle_status=DocumentLifecycleStatus.active,
    )
    generation = types.SimpleNamespace(
        id=generation_id,
        document_id=document_id,
        status=GenerationStatus.pending,
        error="old error",
        activated_at=None,
    )
    previous = types.SimpleNamespace(id=previous_id, status=GenerationStatus.active)
    session = _Session(document, generation, previous)

    await generations.activate_generation(
        session,  # type: ignore[arg-type]
        document_id=document_id,
        generation_id=generation_id,
        vector_ids=["v1", "v1", "v2"],
    )

    assert generation.status == GenerationStatus.active
    assert previous.status == GenerationStatus.superseded
    assert document.active_generation_id == generation_id
    assert document.status == IngestionStatus.ready
    assert session.commits == 1
    manifests = [
        item
        for item in session.added
        if item.__class__.__name__ == "GenerationVectorManifest"
    ]
    purge_jobs = [
        item for item in session.added if item.__class__.__name__ == "PurgeJob"
    ]
    assert len(manifests) == 2
    assert len(purge_jobs) == 1
    assert purge_jobs[0].status == PurgeJobStatus.queued


@pytest.mark.asyncio
async def test_activate_generation_fences_deleting_document_and_queues_cleanup() -> (
    None
):
    document_id = uuid.uuid4()
    generation_id = uuid.uuid4()
    document = types.SimpleNamespace(
        id=document_id,
        active_generation_id=None,
        status=IngestionStatus.processing,
        lifecycle_status=DocumentLifecycleStatus.deleting,
    )
    generation = types.SimpleNamespace(
        id=generation_id,
        document_id=document_id,
        status=GenerationStatus.pending,
        error=None,
        activated_at=None,
    )
    session = _Session(document, generation, None)

    activated = await generations.activate_generation(
        session,  # type: ignore[arg-type]
        document_id=document_id,
        generation_id=generation_id,
        vector_ids=["v1"],
    )

    assert activated is False
    assert generation.status == GenerationStatus.failed
    assert any(item.__class__.__name__ == "PurgeJob" for item in session.added)
