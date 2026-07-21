import types
import uuid
from datetime import UTC, datetime

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.models.entities import (
    DocumentLifecycleStatus,
    GenerationStatus,
    IngestionStatus,
)
from app.services import document_processor
from app.services import ingestion_worker as worker_service


class DummyRedis:
    def __init__(self, *, blpop_result=None):
        self._blpop_result = blpop_result
        self.rpush_calls: list[tuple[str, str]] = []

    async def rpush(self, queue_key: str, value: str):
        self.rpush_calls.append((queue_key, value))

    async def blpop(self, queue_key: str, timeout: int):
        _ = (queue_key, timeout)
        return self._blpop_result


class TimeoutRedis(DummyRedis):
    async def blpop(self, queue_key: str, timeout: int):
        _ = queue_key, timeout
        raise RedisTimeoutError("read timed out")


class DummySession:
    def __init__(self, *, rows: list[tuple[object, object]]):
        self._rows = [
            (
                *row,
                types.SimpleNamespace(id=uuid.uuid4(), status=GenerationStatus.pending),
            )
            if len(row) == 2
            else row
            for row in rows
        ]
        self.commits = 0
        self.rollbacks = 0
        self.refresh_calls: list[object] = []
        self.added: list[object] = []

    async def execute(self, _query):
        row = self._rows.pop(0) if self._rows else None

        class _Result:
            def __init__(self, value):
                self._value = value

            def first(self):
                return self._value

        return _Result(row)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, item):
        self.refresh_calls.append(item)

    async def scalar(self, _query):
        # Failed-generation purge lookup: no existing job in this test double.
        return None

    def add(self, item):
        self.added.append(item)
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()

    async def flush(self):
        return None


class DummyJob:
    def __init__(
        self,
        *,
        status: IngestionStatus,
        attempts: int = 0,
    ):
        self.id = uuid.uuid4()
        self.status = status
        self.attempts = attempts
        self.started_at = None
        self.completed_at = None
        self.error = None
        self.next_attempt_at = None
        self.created_at = datetime.now(UTC)
        self.generation_id = uuid.uuid4()


class DummyDocument:
    def __init__(self, *, status: IngestionStatus):
        self.id = uuid.uuid4()
        self.status = status
        self.active_generation_id = None
        self.lifecycle_status = DocumentLifecycleStatus.active


@pytest.mark.asyncio
async def test_enqueue_ingestion_job_pushes_to_redis_queue() -> None:
    redis_client = DummyRedis()
    job_id = uuid.uuid4()

    await worker_service.enqueue_ingestion_job(
        redis_client,
        queue_key="ingestion:jobs",
        job_id=job_id,
    )

    assert redis_client.rpush_calls == [("ingestion:jobs", str(job_id))]


@pytest.mark.asyncio
async def test_dequeue_timeout_uses_database_fallback() -> None:
    job_id = await worker_service.dequeue_ingestion_job(
        TimeoutRedis(),
        queue_key="ingestion:jobs",
        timeout_seconds=5,
    )

    assert job_id is None


@pytest.mark.asyncio
async def test_claim_ingestion_job_moves_status_to_processing() -> None:
    job = DummyJob(status=IngestionStatus.queued, attempts=0)
    document = DummyDocument(status=IngestionStatus.queued)
    session = DummySession(rows=[(job, document)])

    claimed = await worker_service.claim_ingestion_job(session, job_id=job.id)

    assert claimed is not None
    assert claimed.job.status == IngestionStatus.processing
    assert claimed.document.status == IngestionStatus.processing
    assert claimed.job.attempts == 1
    assert claimed.job.started_at is not None
    assert session.commits == 1
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_claim_ingestion_job_skips_non_queued_job() -> None:
    job = DummyJob(status=IngestionStatus.processing, attempts=1)
    document = DummyDocument(status=IngestionStatus.processing)
    session = DummySession(rows=[(job, document)])

    claimed = await worker_service.claim_ingestion_job(session, job_id=job.id)

    assert claimed is None
    assert session.rollbacks == 1
    assert session.commits == 0


@pytest.mark.asyncio
async def test_claim_ingestion_job_fences_deleting_document_and_queues_purge() -> None:
    job = DummyJob(status=IngestionStatus.queued, attempts=0)
    document = DummyDocument(status=IngestionStatus.queued)
    document.lifecycle_status = DocumentLifecycleStatus.deleting
    generation = types.SimpleNamespace(
        id=job.generation_id,
        status=GenerationStatus.pending,
        error=None,
    )
    session = DummySession(rows=[(job, document, generation)])

    claimed = await worker_service.claim_ingestion_job(session, job_id=job.id)

    assert claimed is None
    assert job.status == IngestionStatus.failed
    assert generation.status == GenerationStatus.failed
    assert any(item.__class__.__name__ == "PurgeJob" for item in session.added)


@pytest.mark.asyncio
async def test_recover_stuck_active_generation_marks_job_ready() -> None:
    job = DummyJob(status=IngestionStatus.processing, attempts=1)
    job.started_at = datetime(2020, 1, 1, tzinfo=UTC)
    document = DummyDocument(status=IngestionStatus.processing)
    document.active_generation_id = job.generation_id
    generation = types.SimpleNamespace(
        id=job.generation_id,
        status=GenerationStatus.active,
        error=None,
    )

    class RecoverySession:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        async def execute(self, _query):
            class Result:
                def all(self):
                    return [(job, document, generation)]

            return Result()

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

    session = RecoverySession()
    recovered = await worker_service.recover_stuck_ingestion_jobs(
        session,  # type: ignore[arg-type]
        stuck_timeout_seconds=1,
        max_attempts=3,
        retry_base_seconds=1,
        retry_max_seconds=10,
    )

    assert recovered == 1
    assert job.status == IngestionStatus.ready
    assert job.completed_at is not None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_recover_stuck_pending_generation_requeues_safely() -> None:
    job = DummyJob(status=IngestionStatus.processing, attempts=1)
    job.started_at = datetime(2020, 1, 1, tzinfo=UTC)
    document = DummyDocument(status=IngestionStatus.processing)
    generation = types.SimpleNamespace(
        id=job.generation_id,
        status=GenerationStatus.pending,
        error=None,
    )

    class RecoverySession:
        async def execute(self, _query):
            class Result:
                def all(self):
                    return [(job, document, generation)]

            return Result()

        async def commit(self):
            return None

        async def rollback(self):
            return None

    recovered = await worker_service.recover_stuck_ingestion_jobs(
        RecoverySession(),  # type: ignore[arg-type]
        stuck_timeout_seconds=1,
        max_attempts=3,
        retry_base_seconds=1,
        retry_max_seconds=10,
    )

    assert recovered == 1
    assert job.status == IngestionStatus.queued
    assert job.next_attempt_at is not None
    assert document.status == IngestionStatus.queued


@pytest.mark.asyncio
async def test_recover_stuck_job_for_deleting_document_queues_cleanup() -> None:
    job = DummyJob(status=IngestionStatus.processing, attempts=1)
    job.started_at = datetime(2020, 1, 1, tzinfo=UTC)
    document = DummyDocument(status=IngestionStatus.processing)
    document.lifecycle_status = DocumentLifecycleStatus.deleting
    generation = types.SimpleNamespace(
        id=job.generation_id,
        status=GenerationStatus.pending,
        error=None,
    )

    class RecoverySession:
        def __init__(self):
            self.added: list[object] = []

        async def execute(self, _query):
            class Result:
                def all(self):
                    return [(job, document, generation)]

            return Result()

        async def scalar(self, _query):
            return None

        def add(self, item):
            self.added.append(item)
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()

        async def flush(self):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

    session = RecoverySession()
    recovered = await worker_service.recover_stuck_ingestion_jobs(
        session,  # type: ignore[arg-type]
        stuck_timeout_seconds=1,
        max_attempts=3,
        retry_base_seconds=1,
        retry_max_seconds=10,
    )

    assert recovered == 1
    assert job.status == IngestionStatus.failed
    assert generation.status == GenerationStatus.failed
    assert any(item.__class__.__name__ == "PurgeJob" for item in session.added)


@pytest.mark.asyncio
async def test_mark_ingestion_job_ready_sets_terminal_ready() -> None:
    job = DummyJob(status=IngestionStatus.processing, attempts=1)
    document = DummyDocument(status=IngestionStatus.processing)
    session = DummySession(rows=[(job, document)])

    await worker_service.mark_ingestion_job_ready(session, job_id=job.id)

    assert job.status == IngestionStatus.ready
    assert document.status == IngestionStatus.ready
    assert job.completed_at is not None
    assert job.error is None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_mark_ingestion_job_ready_updates_active_generation_document() -> None:
    job = DummyJob(status=IngestionStatus.processing, attempts=1)
    document = DummyDocument(status=IngestionStatus.processing)
    document.active_generation_id = uuid.uuid4()
    session = DummySession(rows=[(job, document)])

    await worker_service.mark_ingestion_job_ready(session, job_id=job.id)

    assert job.status == IngestionStatus.ready
    assert document.status == IngestionStatus.ready


@pytest.mark.asyncio
async def test_mark_ingestion_job_retry_or_failed_requeues_when_attempts_remaining() -> (
    None
):
    job = DummyJob(status=IngestionStatus.processing, attempts=1)
    document = DummyDocument(status=IngestionStatus.processing)
    session = DummySession(rows=[(job, document)])

    requeued = await worker_service.mark_ingestion_job_retry_or_failed(
        session,
        job_id=job.id,
        error_message="temporary upstream timeout",
        max_attempts=3,
    )

    assert requeued is True
    assert job.status == IngestionStatus.queued
    assert document.status == IngestionStatus.queued
    assert job.completed_at is None
    assert job.error == "temporary upstream timeout"
    assert job.next_attempt_at is not None


@pytest.mark.asyncio
async def test_mark_ingestion_job_retry_or_failed_marks_failed_at_max_attempts() -> (
    None
):
    job = DummyJob(status=IngestionStatus.processing, attempts=3)
    document = DummyDocument(status=IngestionStatus.processing)
    session = DummySession(rows=[(job, document)])

    requeued = await worker_service.mark_ingestion_job_retry_or_failed(
        session,
        job_id=job.id,
        error_message="permanent parse failure",
        max_attempts=3,
    )

    assert requeued is False
    assert job.status == IngestionStatus.failed
    assert document.status == IngestionStatus.failed
    assert job.completed_at is not None
    assert job.error == "permanent parse failure"
    assert any(item.__class__.__name__ == "PurgeJob" for item in session.added)


@pytest.mark.asyncio
async def test_process_next_ingestion_job_requeues_on_retryable_error() -> None:
    job = DummyJob(status=IngestionStatus.queued, attempts=0)
    document = DummyDocument(status=IngestionStatus.queued)
    session = DummySession(rows=[(job, document), (job, document)])
    redis_client = DummyRedis(blpop_result=("ingestion:jobs", str(job.id)))

    async def _processor(_session, _claimed):
        raise worker_service.RetryableIngestionError("transient rate limit")

    processed = await worker_service.process_next_ingestion_job(
        session,
        redis_client=redis_client,
        queue_key="ingestion:jobs",
        dequeue_timeout_seconds=1,
        max_attempts=3,
        processor=_processor,
    )

    assert processed is True
    assert job.status == IngestionStatus.queued
    assert redis_client.rpush_calls[-1] == ("ingestion:jobs", str(job.id))


@pytest.mark.asyncio
async def test_process_next_ingestion_job_persists_chunks_before_ready_transition() -> (
    None
):
    class PersistingSession:
        def __init__(self, *, job_obj, document_obj):
            self.job_obj = job_obj
            self.document_obj = document_obj
            self.commits = 0
            self.rollbacks = 0
            self.refresh_calls: list[object] = []
            self.added: list[object] = []
            self.delete_executed = False

        async def execute(self, query):
            query_name = query.__class__.__name__

            class _Result:
                def __init__(self, value):
                    self._value = value

                def first(self):
                    return self._value

            if query_name == "Delete":
                self.delete_executed = True
                return _Result(None)
            return _Result(
                (
                    self.job_obj,
                    self.document_obj,
                    types.SimpleNamespace(
                        id=self.job_obj.generation_id,
                        status=GenerationStatus.pending,
                    ),
                )
            )

        async def commit(self):
            self.commits += 1

        async def rollback(self):
            self.rollbacks += 1

        async def refresh(self, item):
            self.refresh_calls.append(item)

        async def scalar(self, _query):
            return None

        def add(self, value):
            self.added.append(value)

    job = DummyJob(status=IngestionStatus.queued, attempts=0)
    document = DummyDocument(status=IngestionStatus.queued)
    session = PersistingSession(job_obj=job, document_obj=document)
    redis_client = DummyRedis(blpop_result=("ingestion:jobs", str(job.id)))

    async def _processor(worker_session, claimed):
        assert claimed.job.id == job.id
        chunks = [
            document_processor.ChunkPayload(
                chunk_index=0,
                chunk_text="chunk text",
                token_count=2,
                metadata={"source_file": "notes.txt", "chunk_index": 0},
            )
        ]
        inserted = await document_processor.replace_document_chunks(
            worker_session,
            document_id=claimed.document.id,
            chunks=chunks,
        )
        assert inserted == 1

    processed = await worker_service.process_next_ingestion_job(
        session,  # type: ignore[arg-type]
        redis_client=redis_client,
        queue_key="ingestion:jobs",
        dequeue_timeout_seconds=1,
        max_attempts=3,
        processor=_processor,
    )

    assert processed is True
    assert session.delete_executed is True
    assert len(session.added) == 1
    assert job.status == IngestionStatus.ready
    assert document.status == IngestionStatus.ready
    assert session.commits == 2
    assert session.rollbacks == 0
