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


def _document_result(*, filename: str, collection_id: uuid.UUID | None = None):
    return types.SimpleNamespace(
        document=types.SimpleNamespace(
            id=uuid.uuid4(),
            filename=filename,
            status=types.SimpleNamespace(value="queued"),
            collection_id=collection_id,
            created_at=datetime.now(UTC),
            file_size=1024,
        ),
        chunk_count=0,
    )


@pytest.mark.asyncio
async def test_upload_document_happy_path(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_enqueues: list[str] = []

    async def _create(_session, **_kwargs):
        return types.SimpleNamespace(
            document=types.SimpleNamespace(id=uuid.uuid4(), filename="notes.txt"),
            job=types.SimpleNamespace(id=uuid.uuid4()),
            deduplicated=False,
            enqueue_job=True,
        )

    async def _enqueue(_redis, *, queue_key: str, job_id: uuid.UUID):
        captured_enqueues.append(f"{queue_key}:{job_id}")

    monkeypatch.setattr(document_service, "create_uploaded_document", _create)
    monkeypatch.setattr(ingestion_worker_service, "enqueue_ingestion_job", _enqueue)

    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    response = await api_client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["filename"] == "notes.txt"
    assert body["document_id"]
    assert body["deduplicated"] is False
    assert body["reused_existing_job"] is False
    assert body["job_id"]
    assert len(captured_enqueues) == 1


@pytest.mark.asyncio
async def test_upload_document_duplicate_returns_existing_result_without_enqueue(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_enqueues: list[str] = []

    async def _create(_session, **_kwargs):
        return types.SimpleNamespace(
            document=types.SimpleNamespace(id=uuid.uuid4(), filename="notes.txt"),
            job=types.SimpleNamespace(
                id=uuid.uuid4(),
                status=types.SimpleNamespace(value="ready"),
            ),
            deduplicated=True,
            enqueue_job=False,
        )

    async def _enqueue(_redis, *, queue_key: str, job_id: uuid.UUID):
        captured_enqueues.append(f"{queue_key}:{job_id}")

    monkeypatch.setattr(document_service, "create_uploaded_document", _create)
    monkeypatch.setattr(ingestion_worker_service, "enqueue_ingestion_job", _enqueue)

    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    response = await api_client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["deduplicated"] is True
    assert body["reused_existing_job"] is True
    assert "Duplicate document detected" in body["message"]
    assert captured_enqueues == []


@pytest.mark.asyncio
async def test_upload_document_duplicate_active_job_returns_202(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_enqueues: list[str] = []

    async def _create(_session, **_kwargs):
        return types.SimpleNamespace(
            document=types.SimpleNamespace(id=uuid.uuid4(), filename="notes.txt"),
            job=types.SimpleNamespace(
                id=uuid.uuid4(),
                status=types.SimpleNamespace(value="processing"),
            ),
            deduplicated=True,
            enqueue_job=False,
        )

    async def _enqueue(_redis, *, queue_key: str, job_id: uuid.UUID):
        captured_enqueues.append(f"{queue_key}:{job_id}")

    monkeypatch.setattr(document_service, "create_uploaded_document", _create)
    monkeypatch.setattr(ingestion_worker_service, "enqueue_ingestion_job", _enqueue)

    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    response = await api_client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processing"
    assert body["deduplicated"] is True
    assert body["reused_existing_job"] is True
    assert "existing active ingestion job" in body["message"]
    assert captured_enqueues == []


@pytest.mark.asyncio
async def test_upload_document_auth_failure(api_client: AsyncClient) -> None:
    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    response = await api_client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == "HTTP_ERROR"


@pytest.mark.asyncio
async def test_upload_document_unsupported_type(
    api_client: AsyncClient,
    override_auth_and_db,
) -> None:
    files = {"file": ("image.png", b"binary", "image/png")}
    response = await api_client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 415


@pytest.mark.asyncio
async def test_upload_document_payload_too_large(
    api_client: AsyncClient,
    override_auth_and_db,
) -> None:
    files = {
        "file": (
            "large.txt",
            b"x" * (10 * 1024 * 1024 + 1),
            "text/plain",
        )
    }
    response = await api_client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_upload_document_collection_not_found(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _create(_session, **_kwargs):
        raise document_service.CollectionNotFoundError("Collection not found")

    monkeypatch.setattr(document_service, "create_uploaded_document", _create)
    files = {"file": ("notes.txt", b"hello world", "text/plain")}
    response = await api_client.post(
        f"/api/v1/documents/upload?collection_id={uuid.uuid4()}",
        files=files,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_documents_happy_path(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _list(_session, **_kwargs):
        return [_document_result(filename="notes.txt")], 1

    monkeypatch.setattr(document_service, "list_documents", _list)
    response = await api_client.get("/api/v1/documents")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["documents"][0]["filename"] == "notes.txt"


@pytest.mark.asyncio
async def test_list_documents_collection_not_found(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _list(_session, **_kwargs):
        raise document_service.CollectionNotFoundError("Collection not found")

    monkeypatch.setattr(document_service, "list_documents", _list)
    response = await api_client.get(f"/api/v1/documents?collection_id={uuid.uuid4()}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_document_not_found(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session, **_kwargs):
        raise document_service.DocumentNotFoundError("Document not found")

    monkeypatch.setattr(document_service, "get_document", _get)
    response = await api_client.get(f"/api/v1/documents/{uuid.uuid4()}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_document_success(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _delete(_session, **_kwargs):
        return None

    monkeypatch.setattr(document_service, "delete_document", _delete)
    response = await api_client.delete(f"/api/v1/documents/{uuid.uuid4()}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Document deleted successfully"


@pytest.mark.asyncio
async def test_delete_document_not_found(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _delete(_session, **_kwargs):
        raise document_service.DocumentNotFoundError("Document not found")

    monkeypatch.setattr(document_service, "delete_document", _delete)
    response = await api_client.delete(f"/api/v1/documents/{uuid.uuid4()}")

    assert response.status_code == 404
