from functools import lru_cache

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
    auth0_audience: str
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
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg driver")
        if "sslmode=require" not in value:
            raise ValueError(
                "DATABASE_URL must include sslmode=require for Supabase Postgres"
            )
        return value

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
