from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_name: str = "Meridian API"
    environment: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # Database
    database_url: str

    # Redis
    redis_url: str

    # OpenAI
    openai_api_key: str

    # Pinecone
    pinecone_api_key: str
    pinecone_index_name: str = "rag-documents"

    # Auth0
    auth0_domain: str
    auth0_audience: str = "https://api.meridian.app"
    auth0_client_id: str

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

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
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(sorted(supported))}")
        return upper


@lru_cache
def get_settings() -> Settings:
    return Settings()
