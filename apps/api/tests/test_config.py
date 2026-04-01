import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres.ref:password@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require",
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("PINECONE_API_KEY", "test-pinecone-key")
    monkeypatch.setenv("AUTH0_DOMAIN", "example.auth0.com")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "test-client-id")


def test_settings_load_with_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["http://localhost:3000", "https://app.example.com"]',
    )

    settings = Settings()

    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.log_level == "INFO"
    assert settings.cors_origins == [
        "http://localhost:3000",
        "https://app.example.com",
    ]


def test_settings_reject_non_supabase_ssl_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres.ref:password@aws-0-ap-south-1.pooler.supabase.com:6543/postgres",
    )

    with pytest.raises(ValidationError):
        Settings()


def test_settings_reject_invalid_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres.ref:password@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require",
    )

    with pytest.raises(ValidationError):
        Settings()
