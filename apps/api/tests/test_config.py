import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.helpers import set_required_env


def test_settings_load_with_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    set_required_env(monkeypatch)
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
    assert settings.chat_model == "openrouter/free"
    assert settings.openrouter_base_url == "https://openrouter.ai/api/v1"


def test_settings_normalizes_openrouter_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/")

    assert Settings().openrouter_base_url == "https://openrouter.ai/api/v1"


def test_settings_reject_non_supabase_ssl_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://test_user:test_password@db.example.com:5432/test_db",
    )

    with pytest.raises(ValidationError):
        Settings()


def test_settings_reject_invalid_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql://user:pass@localhost:3306/db",
    )

    with pytest.raises(ValidationError):
        Settings()


def test_settings_normalize_sslmode_for_asyncpg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_env(monkeypatch)
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
    set_required_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://test_user:test_password@db.example.com:5432/test_db?channel_binding=require",
    )

    settings = Settings()

    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert "channel_binding=require" not in settings.database_url
    assert "ssl=require" in settings.database_url


def test_settings_require_openai_contextual_config_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("CONTEXTUAL_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("CONTEXTUAL_CHUNKING_PROVIDER", "openai")
    monkeypatch.delenv("CONTEXTUAL_CHUNKING_MODEL", raising=False)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("environment_key", "environment_value"),
    [
        ("CHUNK_CHILD_TARGET_TOKENS", "513"),
        ("CHUNK_CHILD_OVERLAP_TOKENS", "512"),
        ("CHUNK_PARENT_TARGET_TOKENS", "1201"),
    ],
)
def test_settings_reject_invalid_chunk_bounds(
    monkeypatch: pytest.MonkeyPatch,
    environment_key: str,
    environment_value: str,
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv(environment_key, environment_value)

    with pytest.raises(ValidationError):
        Settings()


def test_settings_reject_child_target_larger_than_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("CHUNK_CHILD_TARGET_TOKENS", "512")
    monkeypatch.setenv("CHUNK_CHILD_MAX_TOKENS", "384")

    with pytest.raises(ValidationError, match="CHUNK_CHILD_TARGET_TOKENS"):
        Settings()


def test_settings_supports_explicit_hybrid_shadow_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid_shadow")
    monkeypatch.setenv("RETRIEVAL_EXPANSION_ENABLED", "true")
    monkeypatch.setenv("LEXICAL_DEGRADATION_MODE", "dense_only")
    monkeypatch.setenv("RERANKING_SHADOW_ENABLED", "true")

    settings = Settings()

    assert settings.retrieval_mode == "hybrid_shadow"
    assert settings.retrieval_expansion_enabled is True
    assert settings.lexical_degradation_mode == "dense_only"
    assert settings.reranking_shadow_enabled is True
