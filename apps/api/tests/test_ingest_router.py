import os
import types
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure settings can load when importing app.main
os.environ.setdefault("APP_NAME", "Meridian API")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("API_V1_PREFIX", "/api/v1")
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test_user:test_password@db.example.com:5432/test_db?sslmode=require",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("INGESTION_QUEUE_KEY", "ingestion:jobs")
os.environ.setdefault("INGESTION_WORKER_DEQUEUE_TIMEOUT_SECONDS", "5")
os.environ.setdefault("INGESTION_WORKER_MAX_ATTEMPTS", "3")
os.environ.setdefault("INGESTION_WORKER_IDLE_SLEEP_SECONDS", "1.0")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("PINECONE_API_KEY", "test-pinecone-key")
os.environ.setdefault("PINECONE_INDEX_NAME", "test-index")
os.environ.setdefault("AUTH0_DOMAIN", "example.auth0.com")
os.environ.setdefault("AUTH0_AUDIENCE", "https://api.example.com")
os.environ.setdefault("AUTH0_CLIENT_ID", "test-client-id")

from app.core.auth import get_current_user
from app.core.database import get_db_session
from app.main import app
from app.services import documents as document_service
from app.services import ingestion_worker as ingestion_worker_service


@pytest_asyncio.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def override_auth_and_db():
    async def _current_user_override():
        return types.SimpleNamespace(id=uuid.uuid4())

    async def _db_override():
        yield object()

    app.dependency_overrides[get_current_user] = _current_user_override
    app.dependency_overrides[get_db_session] = _db_override
    app.state.redis = object()
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_queue_ingestion_happy_path(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_enqueues: list[str] = []

    async def _create_job(_session, **_kwargs):
        return types.SimpleNamespace(
            job=types.SimpleNamespace(
                id=uuid.uuid4(), status=types.SimpleNamespace(value="queued")
            ),
            document=types.SimpleNamespace(id=uuid.uuid4()),
            created_new_job=True,
        )

    async def _enqueue(_redis, *, queue_key: str, job_id: uuid.UUID):
        captured_enqueues.append(f"{queue_key}:{job_id}")

    monkeypatch.setattr(document_service, "create_ingestion_job", _create_job)
    monkeypatch.setattr(ingestion_worker_service, "enqueue_ingestion_job", _enqueue)

    response = await api_client.post(
        "/api/v1/ingest",
        json={"document_id": str(uuid.uuid4())},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["job_id"]
    assert payload["reused_existing_job"] is False
    assert payload["message"] == "Ingestion job queued"
    assert len(captured_enqueues) == 1


@pytest.mark.asyncio
async def test_queue_ingestion_returns_existing_active_job(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_enqueues: list[str] = []
    existing_job_id = uuid.uuid4()
    existing_document_id = uuid.uuid4()

    async def _create_job(_session, **_kwargs):
        return types.SimpleNamespace(
            job=types.SimpleNamespace(
                id=existing_job_id,
                status=types.SimpleNamespace(value="processing"),
            ),
            document=types.SimpleNamespace(id=existing_document_id),
            created_new_job=False,
        )

    async def _enqueue(_redis, *, queue_key: str, job_id: uuid.UUID):
        captured_enqueues.append(f"{queue_key}:{job_id}")

    monkeypatch.setattr(document_service, "create_ingestion_job", _create_job)
    monkeypatch.setattr(ingestion_worker_service, "enqueue_ingestion_job", _enqueue)

    response = await api_client.post(
        "/api/v1/ingest",
        json={"document_id": str(existing_document_id)},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["job_id"] == str(existing_job_id)
    assert payload["document_id"] == str(existing_document_id)
    assert payload["status"] == "processing"
    assert payload["reused_existing_job"] is True
    assert payload["message"] == "Existing active ingestion job returned"
    assert captured_enqueues == []


@pytest.mark.asyncio
async def test_queue_ingestion_auth_failure(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/ingest",
        json={"document_id": str(uuid.uuid4())},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_queue_ingestion_not_found(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _create_job(_session, **_kwargs):
        raise document_service.DocumentNotFoundError("Document not found")

    monkeypatch.setattr(document_service, "create_ingestion_job", _create_job)
    response = await api_client.post(
        "/api/v1/ingest",
        json={"document_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_queue_ingestion_validation_error(
    api_client: AsyncClient,
    override_auth_and_db,
) -> None:
    response = await api_client.post(
        "/api/v1/ingest",
        json={"document_id": "not-a-uuid"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_ingestion_job_happy_path(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get_job(_session, **_kwargs):
        return types.SimpleNamespace(
            job=types.SimpleNamespace(
                id=uuid.uuid4(),
                status=types.SimpleNamespace(value="processing"),
                attempts=1,
                error=None,
                started_at=datetime.now(UTC),
                completed_at=None,
                created_at=datetime.now(UTC),
            ),
            document=types.SimpleNamespace(id=uuid.uuid4()),
        )

    monkeypatch.setattr(document_service, "get_ingestion_job", _get_job)
    response = await api_client.get(f"/api/v1/ingest/{uuid.uuid4()}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "processing"
    assert payload["attempts"] == 1


@pytest.mark.asyncio
async def test_get_ingestion_job_not_found(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get_job(_session, **_kwargs):
        raise document_service.IngestionJobNotFoundError("Ingestion job not found")

    monkeypatch.setattr(document_service, "get_ingestion_job", _get_job)
    response = await api_client.get(f"/api/v1/ingest/{uuid.uuid4()}")

    assert response.status_code == 404
