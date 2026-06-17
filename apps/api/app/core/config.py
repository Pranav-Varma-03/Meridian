import json
from functools import lru_cache
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_name: str
    environment: str
    debug: bool
    api_v1_prefix: str
    log_level: str

    # Database
    database_url: str

    # Redis
    redis_url: str
    ingestion_queue_key: str
    ingestion_worker_dequeue_timeout_seconds: int
    ingestion_worker_max_attempts: int
    ingestion_worker_idle_sleep_seconds: float

    # OpenAI
    openai_api_key: str | None = None

    # Embeddings (provider-agnostic)
    embedding_provider: str
    embedding_model: str
    embedding_input_type: str | None = None
    contextual_embedding_enabled: bool = False
    contextual_chunking_provider: str = "native"
    contextual_chunking_model: str | None = None

    # Pinecone
    pinecone_api_key: str
    pinecone_index_name: str

    # Auth0
    auth0_domain: str
    auth0_audience: str
    auth0_client_id: str

    # CORS
    cors_origins: Annotated[list[str], NoDecode]

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [
                        str(origin).strip() for origin in parsed if str(origin).strip()
                    ]
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        normalized = value.strip()

        # Accept common Postgres URL forms and normalize to SQLAlchemy asyncpg.
        if normalized.startswith("postgresql://"):
            normalized = normalized.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif normalized.startswith("postgres://"):
            normalized = normalized.replace("postgres://", "postgresql+asyncpg://", 1)

        if not normalized.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use a PostgreSQL URL (postgresql:// or postgresql+asyncpg://)"
            )

        # Enforce secure DB transport.
        # Supabase commonly uses `sslmode=require`, while some providers include
        # `channel_binding=require` for libpq clients. asyncpg does not accept
        # libpq-only query args directly.
        if (
            "sslmode=require" not in normalized
            and "ssl=require" not in normalized
            and "channel_binding=require" not in normalized
        ):
            raise ValueError(
                "DATABASE_URL must include sslmode=require, ssl=require, or channel_binding=require"
            )

        # Normalize query params for asyncpg compatibility.
        split = urlsplit(normalized)
        query_items = parse_qsl(split.query, keep_blank_values=True)

        normalized_query: list[tuple[str, str]] = []
        has_ssl = False
        for key, param_value in query_items:
            lower_key = key.lower()
            if lower_key == "sslmode":
                if param_value.lower() == "require":
                    normalized_query.append(("ssl", "require"))
                    has_ssl = True
                # Ignore non-require sslmode values to avoid insecure startup.
                continue

            if lower_key == "channel_binding":
                # libpq-specific parameter; asyncpg connect() doesn't accept it.
                # Treat require as a signal to enforce TLS.
                if param_value.lower() == "require" and not has_ssl:
                    normalized_query.append(("ssl", "require"))
                    has_ssl = True
                continue

            if lower_key == "ssl":
                has_ssl = True

            normalized_query.append((key, param_value))

        if not has_ssl:
            normalized_query.append(("ssl", "require"))

        normalized = urlunsplit(
            (
                split.scheme,
                split.netloc,
                split.path,
                urlencode(normalized_query),
                split.fragment,
            )
        )

        return normalized

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        supported = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = value.upper()
        if upper not in supported:
            raise ValueError(
                f"LOG_LEVEL must be one of: {', '.join(sorted(supported))}"
            )
        return upper

    @field_validator("embedding_provider")
    @classmethod
    def validate_embedding_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        supported = {"pinecone", "openai"}
        if normalized not in supported:
            raise ValueError(
                f"EMBEDDING_PROVIDER must be one of: {', '.join(sorted(supported))}"
            )
        return normalized

    @field_validator("embedding_model")
    @classmethod
    def validate_embedding_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("EMBEDDING_MODEL must be a non-empty string")
        return normalized

    @field_validator("embedding_input_type")
    @classmethod
    def validate_embedding_input_type(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip().lower()
        if not normalized:
            return None

        supported = {"passage", "query"}
        if normalized not in supported:
            raise ValueError(
                f"EMBEDDING_INPUT_TYPE must be one of: {', '.join(sorted(supported))}"
            )
        return normalized

    @field_validator("contextual_chunking_provider")
    @classmethod
    def validate_contextual_chunking_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        supported = {"native", "openai"}
        if normalized not in supported:
            raise ValueError(
                "CONTEXTUAL_CHUNKING_PROVIDER must be one of: native, openai"
            )
        return normalized

    @model_validator(mode="after")
    def validate_embedding_configuration(self) -> "Settings":
        if (
            self.embedding_provider == "pinecone"
            and self.embedding_model == "llama-text-embed-v2"
            and not self.embedding_input_type
        ):
            raise ValueError(
                "EMBEDDING_INPUT_TYPE is required for pinecone model llama-text-embed-v2"
            )

        if (
            self.contextual_embedding_enabled
            and self.contextual_chunking_provider == "openai"
            and (not self.contextual_chunking_model or not self.openai_api_key)
        ):
            raise ValueError(
                "OpenAI contextual chunking requires CONTEXTUAL_CHUNKING_MODEL and OPENAI_API_KEY"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
