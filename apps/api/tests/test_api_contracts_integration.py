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


@pytest.mark.asyncio
async def test_openapi_contract_status_codes(api_client: AsyncClient) -> None:
    response = await api_client.get("/openapi.json")
    assert response.status_code == 200

    paths = response.json()["paths"]

    assert paths["/api/v1/collections"]["post"]["responses"].get("201")
    assert paths["/api/v1/documents/upload"]["post"]["responses"].get("202")
    assert paths["/api/v1/documents/{document_id}"]["delete"]["responses"].get("200")
    assert paths["/api/v1/chat"]["post"]["responses"].get("200")


@pytest.mark.asyncio
async def test_users_me_unauthorized_error_envelope(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/users/me")

    assert response.status_code == 401
    payload = response.json()
    assert "error" in payload
    assert payload["error"]["code"] == "HTTP_ERROR"
    assert payload["error"]["request_id"]


@pytest.mark.asyncio
async def test_collections_create_contract_response(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _current_user_override():
        return types.SimpleNamespace(id=uuid.uuid4())

    async def _db_override():
        yield object()

    async def _create(_session, *, user_id, name, description):
        collection = types.SimpleNamespace(
            id=uuid.uuid4(),
            name=name,
            description=description,
            created_at=datetime.now(UTC),
        )
        return types.SimpleNamespace(collection=collection, document_count=0)

    monkeypatch.setattr(collection_service, "create_collection", _create)
    app.dependency_overrides[get_current_user] = _current_user_override
    app.dependency_overrides[get_db_session] = _db_override

    try:
        response = await api_client.post(
            "/api/v1/collections",
            json={"name": "Product Docs", "description": "Team docs"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Product Docs"
        assert "id" in body
        assert "created_at" in body
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_documents_upload_contract_accepts_txt(api_client: AsyncClient) -> None:
    files = {"file": ("notes.txt", b"hello world", "text/plain")}

    response = await api_client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_id"]


@pytest.mark.asyncio
async def test_documents_upload_rejects_unsupported_type(
    api_client: AsyncClient,
) -> None:
    files = {"file": ("image.png", b"binary", "image/png")}

    response = await api_client.post("/api/v1/documents/upload", files=files)

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "HTTP_ERROR"


@pytest.mark.asyncio
async def test_chat_sse_contract_shape(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/chat", json={"query": "hello"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"type": "done"' in response.text


@pytest.mark.asyncio
async def test_users_me_provision_success_with_dependency_overrides(
    api_client: AsyncClient,
) -> None:
    async def _current_user_override():
        return types.SimpleNamespace(
            id=uuid.uuid4(),
            auth_subject="auth0|integration-user",
            email="integration@example.com",
            created_at=datetime.now(UTC),
        )

    app.dependency_overrides[get_current_user] = _current_user_override

    try:
        response = await api_client.post("/api/v1/users/me")
        assert response.status_code == 200
        body = response.json()
        assert body["auth_subject"] == "auth0|integration-user"
        assert body["email"] == "integration@example.com"
    finally:
        app.dependency_overrides.clear()
