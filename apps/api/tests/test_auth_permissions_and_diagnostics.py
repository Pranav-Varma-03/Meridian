from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from jose import JWTError

from app.core import auth
from app.core.auth import get_current_user_claims, require_permission
from app.main import app
from app.routers import auth_diagnostics


@pytest_asyncio.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_access_token_verification_uses_only_api_audience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_audiences: list[str] = []

    async def _jwks():
        return {"keys": [{"kid": "key-id"}]}

    def _decode(_token, _key, **kwargs):
        captured_audiences.append(kwargs["audience"])
        raise JWTError("wrong audience")

    monkeypatch.setattr(auth, "_get_jwks", _jwks)
    monkeypatch.setattr(
        auth.jwt, "get_unverified_header", lambda _token: {"kid": "key-id"}
    )
    monkeypatch.setattr(auth.jwt, "decode", _decode)

    with pytest.raises(HTTPException) as exc_info:
        await auth.verify_auth0_access_token("access-token")

    assert exc_info.value.status_code == 401
    assert captured_audiences == [auth.settings.auth0_audience]


@pytest.mark.asyncio
async def test_permission_dependency_allows_required_permission() -> None:
    dependency = require_permission("documents:reingest")
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-1"))

    claims = await dependency(
        request=request,
        claims={"permissions": ["documents:reingest"]},
    )

    assert claims["permissions"] == ["documents:reingest"]


@pytest.mark.asyncio
@pytest.mark.parametrize("permissions", [None, "documents:reingest", [123]])
async def test_permission_dependency_rejects_missing_or_malformed_permissions(
    permissions,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dependency = require_permission("documents:reingest")
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-2"))

    with pytest.raises(HTTPException) as exc_info:
        await dependency(request=request, claims={"permissions": permissions})

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Insufficient permissions"
    assert caplog.records[-1].required_permission == "documents:reingest"


@pytest.mark.asyncio
async def test_development_token_claims_returns_allowlisted_verified_claims(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _claims_override():
        return {
            "iss": "https://tenant.example.auth0.com/",
            "aud": "https://api.example.com",
            "permissions": ["documents:reingest", 123],
            "sub": "auth0|sensitive-subject",
            "email": "sensitive@example.com",
        }

    monkeypatch.setattr(auth_diagnostics.settings, "environment", "development")
    app.dependency_overrides[get_current_user_claims] = _claims_override
    try:
        response = await api_client.get("/api/v1/auth/token-claims")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "iss": "https://tenant.example.auth0.com/",
        "aud": "https://api.example.com",
        "permissions": ["documents:reingest"],
    }


@pytest.mark.asyncio
async def test_development_token_claims_requires_valid_bearer_token(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_diagnostics.settings, "environment", "development")

    response = await api_client.get("/api/v1/auth/token-claims")

    assert response.status_code == 401
    assert "error" in response.json()


@pytest.mark.asyncio
async def test_token_claims_route_is_hidden_outside_development(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_diagnostics.settings, "environment", "production")

    response = await api_client.get("/api/v1/auth/token-claims")

    assert response.status_code == 404
    assert "error" in response.json()
