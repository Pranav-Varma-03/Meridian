"""Shared test setup helpers for the Meridian API test suite."""

import pytest


def set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure the minimum valid Settings environment for a test."""
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
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "pinecone")
    monkeypatch.setenv("EMBEDDING_MODEL", "llama-text-embed-v2")
    monkeypatch.setenv("EMBEDDING_INPUT_TYPE", "passage")
    monkeypatch.setenv("CONTEXTUAL_EMBEDDING_ENABLED", "false")
    monkeypatch.setenv("CONTEXTUAL_CHUNKING_PROVIDER", "native")
    monkeypatch.setenv("PINECONE_API_KEY", "test-pinecone-key")
    monkeypatch.setenv("PINECONE_INDEX_NAME", "test-index")
    monkeypatch.setenv("AUTH0_DOMAIN", "example.auth0.com")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")
    monkeypatch.setenv("AUTH0_CLIENT_ID", "test-client-id")
