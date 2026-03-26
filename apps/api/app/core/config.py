from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "Meridian API"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/meridian"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # OpenAI
    openai_api_key: str = ""

    # Pinecone
    pinecone_api_key: str = ""
    pinecone_index_name: str = "rag-documents"

    # Auth0
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_client_id: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
