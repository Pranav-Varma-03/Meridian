from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def test_auth0_client_requests_configured_api_audience() -> None:
    source = (WEB_ROOT / "src/lib/auth0.ts").read_text()

    assert "authorizationParameters" in source
    assert "audience: process.env.AUTH0_AUDIENCE" in source
    assert 'scope: process.env.AUTH0_SCOPE ?? "openid profile email"' in source


def test_web_api_call_uses_access_token_not_id_token() -> None:
    provisioning_source = (WEB_ROOT / "src/lib/server/meridian.ts").read_text()
    bff_source = (WEB_ROOT / "src/lib/server/meridian-bff.ts").read_text()

    # API tokens are intentionally acquired only in server-side helpers. Browser code
    # calls the same-origin BFF and never receives either token type.
    assert "auth0.getAccessToken()" in provisioning_source
    assert "Authorization: `Bearer ${accessToken.token}`" in provisioning_source
    assert "auth0.getAccessToken()" in bff_source
    assert "idToken" not in provisioning_source
    assert "idToken" not in bff_source
