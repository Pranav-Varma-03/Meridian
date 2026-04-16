import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "Meridian API")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("API_V1_PREFIX", "/api/v1")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3000"]')
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://test_user:test_password@db.example.com:5432/test_db?sslmode=require",
    )
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("INGESTION_QUEUE_KEY", "ingestion:jobs")
    monkeypatch.setenv("INGESTION_WORKER_DEQUEUE_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("INGESTION_WORKER_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("INGESTION_WORKER_IDLE_SLEEP_SECONDS", "1.0")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("PINECONE_API_KEY", "test-pinecone-key")
    monkeypatch.setenv("PINECONE_INDEX_NAME", "test-index")
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
        "postgresql+asyncpg://test_user:test_password@db.example.com:5432/test_db",
    )

    with pytest.raises(ValidationError):
        Settings()


def test_settings_reject_invalid_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql://user:pass@localhost:3306/db",
    )

    with pytest.raises(ValidationError):
        Settings()


def test_settings_normalize_sslmode_for_asyncpg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test_user:test_password@db.example.com:5432/test_db?sslmode=require",
    )

    settings = Settings()

    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert "ssl=require" in settings.database_url
    assert "sslmode=require" not in settings.database_url


def test_settings_normalize_channel_binding_for_asyncpg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test_user:test_password@db.example.com:5432/test_db?channel_binding=require",
    )

    settings = Settings()

    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert "channel_binding=require" not in settings.database_url
    assert "ssl=require" in settings.database_url
