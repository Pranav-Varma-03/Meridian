import os
import types
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure settings can load when importing app.main
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres.ref:password@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("INGESTION_QUEUE_KEY", "ingestion:jobs")
os.environ.setdefault("INGESTION_WORKER_DEQUEUE_TIMEOUT_SECONDS", "5")
os.environ.setdefault("INGESTION_WORKER_MAX_ATTEMPTS", "3")
os.environ.setdefault("INGESTION_WORKER_IDLE_SLEEP_SECONDS", "1.0")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("PINECONE_API_KEY", "test-pinecone-key")
os.environ.setdefault("AUTH0_DOMAIN", "example.auth0.com")
os.environ.setdefault("AUTH0_AUDIENCE", "https://api.example.com")
os.environ.setdefault("AUTH0_CLIENT_ID", "test-client-id")

from app.core.auth import get_current_user
from app.core.database import get_db_session
from app.main import app
from app.services import collections as collection_service


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
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def _collection_result(name: str, description: str | None = None):
    collection = types.SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        description=description,
        created_at=datetime.now(UTC),
    )
    return types.SimpleNamespace(collection=collection, document_count=0)


@pytest.mark.asyncio
async def test_create_collection_happy_path(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _create(_session, *, user_id, name, description):
        assert user_id is not None
        return _collection_result(name=name, description=description)

    monkeypatch.setattr(collection_service, "create_collection", _create)

    response = await api_client.post(
        "/api/v1/collections",
        json={"name": "Product Docs", "description": "Team docs"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Product Docs"
    assert body["description"] == "Team docs"
    assert body["document_count"] == 0
    assert body["id"]


@pytest.mark.asyncio
async def test_create_collection_auth_failure(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/collections",
        json={"name": "Product Docs", "description": "Team docs"},
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["error"]["code"] == "HTTP_ERROR"


@pytest.mark.asyncio
async def test_create_collection_validation_error(
    api_client: AsyncClient,
    override_auth_and_db,
) -> None:
    response = await api_client.post(
        "/api/v1/collections",
        json={"name": "", "description": "Team docs"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_collection_conflict(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _create(_session, **_kwargs):
        raise collection_service.CollectionConflictError(
            "Collection with this name already exists"
        )

    monkeypatch.setattr(collection_service, "create_collection", _create)

    response = await api_client.post(
        "/api/v1/collections",
        json={"name": "Product Docs"},
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"]["message"] == "Collection with this name already exists"


@pytest.mark.asyncio
async def test_get_collection_not_found(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _get(_session, **_kwargs):
        raise collection_service.CollectionNotFoundError("Collection not found")

    monkeypatch.setattr(collection_service, "get_collection", _get)

    response = await api_client.get(f"/api/v1/collections/{uuid.uuid4()}")

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["message"] == "Collection not found"


@pytest.mark.asyncio
async def test_update_collection_requires_payload_fields(
    api_client: AsyncClient,
    override_auth_and_db,
) -> None:
    response = await api_client.patch(f"/api/v1/collections/{uuid.uuid4()}", json={})

    assert response.status_code == 400
    payload = response.json()
    assert "At least one field" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_update_collection_conflict(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _update(_session, **_kwargs):
        raise collection_service.CollectionConflictError(
            "Collection with this name already exists"
        )

    monkeypatch.setattr(collection_service, "update_collection", _update)

    response = await api_client.patch(
        f"/api/v1/collections/{uuid.uuid4()}",
        json={"name": "Duplicate Name"},
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"]["message"] == "Collection with this name already exists"


@pytest.mark.asyncio
async def test_delete_collection_success(
    api_client: AsyncClient,
    override_auth_and_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _delete(_session, **_kwargs):
        return None

    monkeypatch.setattr(collection_service, "delete_collection", _delete)

    response = await api_client.delete(f"/api/v1/collections/{uuid.uuid4()}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Collection deleted"
