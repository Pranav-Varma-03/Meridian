from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"


def test_auth0_client_requests_configured_api_audience() -> None:
    source = (WEB_ROOT / "src/lib/auth0.ts").read_text()

    assert "authorizationParameters" in source
    assert "audience: process.env.AUTH0_AUDIENCE" in source
    assert 'scope: process.env.AUTH0_SCOPE ?? "openid profile email"' in source


def test_web_api_call_uses_access_token_not_id_token() -> None:
    source = (WEB_ROOT / "src/app/page.tsx").read_text()

    assert "auth0.getAccessToken()" in source
    assert "session.tokenSet?.idToken" not in source
