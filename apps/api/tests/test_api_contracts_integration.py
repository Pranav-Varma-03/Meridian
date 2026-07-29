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
os.environ.setdefault("EMBEDDING_PROVIDER", "pinecone")
os.environ.setdefault("EMBEDDING_MODEL", "llama-text-embed-v2")
os.environ.setdefault("EMBEDDING_INPUT_TYPE", "passage")
os.environ.setdefault("PINECONE_API_KEY", "test-pinecone-key")
os.environ.setdefault("PINECONE_INDEX_NAME", "test-index")
os.environ.setdefault("AUTH0_DOMAIN", "example.auth0.com")
os.environ.setdefault("AUTH0_AUDIENCE", "https://api.example.com")
os.environ.setdefault("AUTH0_CLIENT_ID", "test-client-id")

from app.core.auth import get_current_user
from app.core.database import get_db_session
from app.main import app
from app.services import collections as collection_service
from app.services import documents as document_service


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

    expected_response_codes = {
        ("/", "get"): {"200"},
        ("/health", "get"): {"200", "500"},
        ("/health/live", "get"): {"200"},
        ("/health/ready", "get"): {"200", "503"},
        ("/api/v1/auth/token-claims", "get"): {"200", "401", "404"},
        ("/api/v1/users/me", "post"): {"200", "401", "500"},
        ("/api/v1/collections", "post"): {"201", "401", "409", "422", "500"},
        ("/api/v1/collections", "get"): {"200", "401", "422", "500"},
        ("/api/v1/collections/{collection_id}", "get"): {
            "200",
            "401",
            "404",
            "422",
            "500",
        },
        ("/api/v1/collections/{collection_id}", "patch"): {
            "200",
            "400",
            "401",
            "404",
            "409",
            "422",
            "500",
        },
        ("/api/v1/collections/{collection_id}", "delete"): {
            "200",
            "401",
            "404",
            "422",
            "500",
        },
        ("/api/v1/documents/upload", "post"): {
            "200",
            "202",
            "401",
            "404",
            "413",
            "415",
            "422",
            "429",
            "500",
            "503",
        },
        ("/api/v1/documents", "get"): {"200", "401", "404", "422", "500"},
        ("/api/v1/documents/{document_id}", "get"): {
            "200",
            "401",
            "404",
            "422",
            "500",
        },
        ("/api/v1/documents/{document_id}", "delete"): {
            "200",
            "401",
            "404",
            "422",
            "500",
        },
        ("/api/v1/ingest", "post"): {
            "202",
            "401",
            "403",
            "404",
            "422",
            "429",
            "500",
            "503",
        },
        ("/api/v1/ingest/{job_id}", "get"): {"200", "401", "404", "422", "500"},
        ("/api/v1/chat", "post"): {
            "200",
            "401",
            "404",
            "422",
            "429",
            "500",
            "503",
        },
        ("/api/v1/chat/conversations", "get"): {"200", "401", "422", "500"},
        ("/api/v1/chat/conversations/{conversation_id}", "get"): {
            "200",
            "401",
            "404",
            "422",
            "500",
        },
        ("/api/v1/chat/conversations/{conversation_id}", "delete"): {
            "200",
            "401",
            "404",
            "422",
            "500",
        },
    }
    for (path, method), expected_codes in expected_response_codes.items():
        assert expected_codes <= set(paths[path][method]["responses"])


@pytest.mark.asyncio
async def test_openapi_examples_describe_current_chat_and_lifecycle_contract(
    api_client: AsyncClient,
) -> None:
    schema = (await api_client.get("/openapi.json")).json()
    paths = schema["paths"]

    chat_content = paths["/api/v1/chat"]["post"]["requestBody"]["content"]
    examples = chat_content["application/json"]["examples"]
    assert examples["all_documents"]["value"]["retrieval_scope"] == {"mode": "all"}
    assert (
        examples["selected_collections"]["value"]["retrieval_scope"]["mode"]
        == "collections"
    )
    assert examples["legacy_collection_ids"]["value"]["collection_ids"]
    assert examples["invalid_conflicting_scopes"]["value"]["retrieval_scope"] == {
        "mode": "all"
    }

    upload = paths["/api/v1/documents/upload"]["post"]
    collection_parameter = next(
        item for item in upload["parameters"] if item["name"] == "collection_id"
    )
    assert collection_parameter["in"] == "query"
    assert "unfiled" in collection_parameter["description"]

    assert (
        "asynchronous"
        in paths["/api/v1/documents/{document_id}"]["delete"]["description"]
    )
    assert (
        "unfiled"
        in paths["/api/v1/collections/{collection_id}"]["delete"]["description"]
    )

    ingestion_responses = paths["/api/v1/ingest"]["post"]["responses"]
    assert ingestion_responses["429"]["headers"]["Retry-After"]
    assert (
        ingestion_responses["503"]["content"]["application/json"]["example"]["error"][
            "code"
        ]
        == "RATE_LIMIT_DEPENDENCY_UNAVAILABLE"
    )
    reingest_examples = paths["/api/v1/ingest"]["post"]["requestBody"]["content"][
        "application/json"
    ]["examples"]
    assert set(reingest_examples) == {
        "manual_repair",
        "model_migration",
        "chunking_change",
    }


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
    async def _current_user_override():
        return types.SimpleNamespace(id=uuid.uuid4())

    async def _db_override():
        yield object()

    async def _create_upload(_session, **_kwargs):
        return types.SimpleNamespace(
            document=types.SimpleNamespace(id=uuid.uuid4(), filename="notes.txt"),
            job=types.SimpleNamespace(id=uuid.uuid4()),
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(document_service, "create_uploaded_document", _create_upload)
    app.dependency_overrides[get_current_user] = _current_user_override
    app.dependency_overrides[get_db_session] = _db_override

    files = {"file": ("notes.txt", b"hello world", "text/plain")}

    try:
        response = await api_client.post("/api/v1/documents/upload", files=files)

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert body["job_id"]
        assert body["document_id"]
        assert body["deduplicated"] is False
    finally:
        monkeypatch.undo()
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_documents_upload_rejects_unsupported_type(
    api_client: AsyncClient,
) -> None:
    async def _current_user_override():
        return types.SimpleNamespace(id=uuid.uuid4())

    async def _db_override():
        yield object()

    app.dependency_overrides[get_current_user] = _current_user_override
    app.dependency_overrides[get_db_session] = _db_override

    files = {"file": ("image.png", b"binary", "image/png")}

    try:
        response = await api_client.post("/api/v1/documents/upload", files=files)

        assert response.status_code == 415
        payload = response.json()
        assert payload["error"]["code"] == "HTTP_ERROR"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_sse_contract_shape(api_client: AsyncClient) -> None:
    response = await api_client.post("/api/v1/chat", json={"query": "hello"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "HTTP_ERROR"


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
