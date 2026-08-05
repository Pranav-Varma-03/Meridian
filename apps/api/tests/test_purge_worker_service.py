import types
import uuid
from datetime import UTC, datetime

import pytest

from app.models.entities import (
    DocumentLifecycleStatus,
    GenerationStatus,
    PurgeJobStatus,
)
from app.services import purge_worker


class _ScalarValues:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values

    def __iter__(self):
        return iter(self._values)


class _Session:
    def __init__(self, *, document, generation, vector_ids):
        self.document = document
        self.generation = generation
        self.vector_ids = vector_ids
        self.commits = 0
        self.executed = []

    async def scalar(self, _statement):
        if not hasattr(self, "_document_returned"):
            self._document_returned = True
            return self.document
        return self.generation

    async def scalars(self, _statement):
        return _ScalarValues(self.vector_ids)

    async def commit(self):
        self.commits += 1

    async def execute(self, statement):
        self.executed.append(statement)


@pytest.mark.asyncio
async def test_generation_purge_reconciles_only_target_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid.uuid4()
    generation_id = uuid.uuid4()
    document = types.SimpleNamespace(
        id=document_id,
        user_id=uuid.uuid4(),
        lifecycle_status=DocumentLifecycleStatus.active,
        metadata_json={},
    )
    generation = types.SimpleNamespace(
        id=generation_id,
        generation_number=4,
        status=GenerationStatus.superseded,
    )
    job = types.SimpleNamespace(
        id=uuid.uuid4(),
        document_id=document_id,
        generation_id=generation_id,
        attempts=1,
        status=PurgeJobStatus.running,
        started_at=datetime.now(UTC),
        next_attempt_at=None,
        completed_at=None,
        last_error=None,
    )
    session = _Session(document=document, generation=generation, vector_ids=["v1"])
    captured_filters = []

    async def _delete_exact(*_args, **_kwargs):
        return None

    async def _delete_filter(*_args, **kwargs):
        captured_filters.append(kwargs["metadata_filter"])

    monkeypatch.setattr(purge_worker.embeddings, "delete_embeddings", _delete_exact)
    monkeypatch.setattr(
        purge_worker.embeddings,
        "delete_embeddings_by_metadata_filter",
        _delete_filter,
    )

    await purge_worker.process_purge_job(
        session,  # type: ignore[arg-type]
        job=job,
        pinecone_client=object(),
        pinecone_index_name="index",
        batch_size=100,
        timeout_seconds=1,
        max_attempts=1,
    )

    assert captured_filters == [{"document_id": str(document_id), "generation": 4}]
    assert generation.status == GenerationStatus.purged
    assert job.status == PurgeJobStatus.complete


@pytest.mark.asyncio
async def test_document_purge_reconciles_all_legacy_document_vectors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    document_id = uuid.uuid4()
    raw_file = tmp_path / "source.txt"
    raw_file.write_text("source", encoding="utf-8")
    document = types.SimpleNamespace(
        id=document_id,
        user_id=uuid.uuid4(),
        lifecycle_status=DocumentLifecycleStatus.deleting,
        metadata_json={"storage_path": str(raw_file)},
    )
    job = types.SimpleNamespace(
        id=uuid.uuid4(),
        document_id=document_id,
        generation_id=None,
        attempts=1,
        status=PurgeJobStatus.running,
        started_at=datetime.now(UTC),
        next_attempt_at=None,
        completed_at=None,
        last_error=None,
    )
    session = _Session(document=document, generation=None, vector_ids=[])
    captured_filters = []

    async def _delete_exact(*_args, **_kwargs):
        return None

    async def _delete_filter(*_args, **kwargs):
        captured_filters.append(kwargs["metadata_filter"])

    monkeypatch.setattr(purge_worker.embeddings, "delete_embeddings", _delete_exact)
    monkeypatch.setattr(
        purge_worker.embeddings,
        "delete_embeddings_by_metadata_filter",
        _delete_filter,
    )

    await purge_worker.process_purge_job(
        session,  # type: ignore[arg-type]
        job=job,
        pinecone_client=object(),
        pinecone_index_name="index",
        batch_size=100,
        timeout_seconds=1,
        max_attempts=1,
    )

    assert captured_filters == [{"document_id": str(document_id)}]
    assert document.lifecycle_status == DocumentLifecycleStatus.deleted
    assert job.status == PurgeJobStatus.complete
    assert not raw_file.exists()


@pytest.mark.asyncio
async def test_structured_generation_purge_removes_only_its_relational_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = uuid.uuid4()
    generation_id = uuid.uuid4()
    document = types.SimpleNamespace(
        id=document_id,
        user_id=uuid.uuid4(),
        lifecycle_status=DocumentLifecycleStatus.active,
        metadata_json={},
    )
    generation = types.SimpleNamespace(
        id=generation_id,
        generation_number=2,
        status=GenerationStatus.failed,
        configuration_json={"chunker": {"strategy": "structure_aware_parent_child_v1"}},
    )
    job = types.SimpleNamespace(
        id=uuid.uuid4(),
        document_id=document_id,
        generation_id=generation_id,
        attempts=1,
        status=PurgeJobStatus.running,
        started_at=datetime.now(UTC),
        next_attempt_at=None,
        completed_at=None,
        last_error=None,
    )
    session = _Session(document=document, generation=generation, vector_ids=["v2"])

    async def _delete_exact(*_args, **_kwargs):
        return None

    async def _delete_filter(*_args, **_kwargs):
        return None

    monkeypatch.setattr(purge_worker.embeddings, "delete_embeddings", _delete_exact)
    monkeypatch.setattr(
        purge_worker.embeddings,
        "delete_embeddings_by_metadata_filter",
        _delete_filter,
    )

    await purge_worker.process_purge_job(
        session,  # type: ignore[arg-type]
        job=job,
        pinecone_client=object(),
        pinecone_index_name="index",
        batch_size=100,
        timeout_seconds=1,
        max_attempts=1,
    )

    assert len(session.executed) == 2
    assert generation.status == GenerationStatus.purged
