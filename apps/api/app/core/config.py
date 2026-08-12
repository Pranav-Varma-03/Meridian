import json
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_name: str
    environment: str
    debug: bool
    api_v1_prefix: str
    log_level: str

    # Observability. The application exports OTLP only to an internal collector;
    # Grafana Alloy owns Grafana Cloud credentials and external network egress.
    observability_enabled: bool = False
    otel_service_name: str = "meridian-api"
    otel_exporter_otlp_traces_endpoint: str | None = None
    otel_exporter_otlp_metrics_endpoint: str | None = None
    otel_exporter_otlp_logs_endpoint: str | None = None
    # These aliases deliberately fail fast when direct-cloud settings leak into
    # a Meridian workload. Grafana Alloy is the sole egress and credential
    # boundary; applications may only authenticate to private collectors.
    forbidden_otlp_headers: str | None = Field(
        default=None,
        validation_alias="OTEL_EXPORTER_OTLP_HEADERS",
        exclude=True,
        repr=False,
    )
    forbidden_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT",
        exclude=True,
        repr=False,
    )
    forbidden_grafana_cloud_endpoint: str | None = Field(
        default=None,
        validation_alias="GRAFANA_CLOUD_OTLP_ENDPOINT",
        exclude=True,
        repr=False,
    )
    forbidden_grafana_cloud_authorization: str | None = Field(
        default=None,
        validation_alias="GRAFANA_CLOUD_OTLP_AUTHORIZATION",
        exclude=True,
        repr=False,
    )
    otel_trace_sample_ratio: float = Field(default=0.1, ge=0, le=1)

    # Database
    database_url: str

    # Redis
    redis_url: str
    ingestion_queue_key: str
    ingestion_worker_dequeue_timeout_seconds: int
    ingestion_worker_max_attempts: int
    ingestion_worker_idle_sleep_seconds: float
    ingestion_retry_base_seconds: float = Field(default=1.0, gt=0, le=300)
    ingestion_retry_max_seconds: float = Field(default=300.0, gt=0, le=3600)
    ingestion_worker_stuck_timeout_seconds: float = Field(default=900.0, gt=0, le=86400)
    purge_worker_stuck_timeout_seconds: float = Field(default=900.0, gt=0, le=86400)

    # Expensive-route protection. Redis coordinates these limits across API instances.
    rate_limit_enabled: bool = True
    chat_rate_limit_requests: int = Field(default=20, gt=0, le=10000)
    chat_rate_limit_window_seconds: int = Field(default=60, gt=0, le=86400)
    upload_rate_limit_requests: int = Field(default=10, gt=0, le=10000)
    upload_rate_limit_window_seconds: int = Field(default=3600, gt=0, le=86400)

    # OpenAI
    openai_api_key: str | None = None

    # OpenRouter powers grounded chat generation. OpenAI remains available for the
    # optional OpenAI embedding and contextual chunking integrations below.
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # The API validates generation-provider availability when a chat request is made
    # so deployments that only run ingestion are not blocked at startup.
    chat_model: str = "openrouter/free"
    chat_temperature: float = Field(default=0.2, ge=0, le=2)
    chat_max_output_tokens: int = Field(default=800, gt=0, le=8192)
    generation_provider_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    chat_context_window_tokens: int = Field(default=16000, gt=1024, le=200000)
    chat_context_budget_tokens: int = Field(default=6000, gt=256, le=100000)
    chat_safety_reserve_tokens: int = Field(default=512, gt=0, le=8192)
    chat_summary_max_tokens: int = Field(default=1000, ge=0, le=16000)
    chat_history_max_tokens: int = Field(default=1800, ge=0, le=32000)
    chat_source_min_tokens: int = Field(default=1200, gt=0, le=32000)
    chat_source_max_tokens: int = Field(default=4000, gt=0, le=64000)
    chat_source_per_document_limit: int = Field(default=2, gt=0, le=10)
    chat_retrieval_top_k: int = Field(default=12, gt=0, le=100)
    chat_retrieval_overfetch: int = Field(default=3, gt=0, le=10)
    chat_retrieval_max_sources: int = Field(default=6, gt=0, le=30)
    chat_retrieval_score_threshold: float = Field(default=0.2, ge=-1, le=1)
    chat_history_max_messages: int = Field(default=8, gt=0, le=50)
    chat_summary_model: str | None = None
    chat_rewrite_model: str | None = None

    # Embeddings (provider-agnostic)
    embedding_provider: str
    embedding_model: str
    embedding_input_type: str | None = None
    contextual_embedding_enabled: bool = False
    contextual_chunking_provider: str = "native"
    contextual_chunking_model: str | None = None

    # Versioned structured-ingestion and retrieval rollout controls. The safe
    # default keeps the currently active dense retrieval behavior unchanged.
    document_parser_provider: Literal["unstructured", "compatibility"] = "unstructured"
    document_parser_fallback_provider: Literal["compatibility"] = "compatibility"
    document_parser_version: str = "unstructured_by_title_v1"
    ingestion_tokenizer_version: str = "cl100k_base"
    chunk_strategy_version: str = "structure_aware_parent_child_v1"
    chunk_child_target_tokens: int = Field(default=384, gt=0, le=512)
    chunk_child_max_tokens: int = Field(default=512, gt=0, le=2048)
    chunk_child_overlap_tokens: int = Field(default=48, ge=0, le=512)
    chunk_parent_target_tokens: int = Field(default=900, gt=0, le=1200)
    chunk_parent_max_tokens: int = Field(default=1200, gt=0, le=4096)
    embedding_text_version: str = "document_section_locator_v1"
    lexical_backend: Literal["postgresql"] = "postgresql"
    lexical_index_version: str = "postgres_simple_v1"
    dense_index_version: str = "dense_child_v1"
    retrieval_mode: Literal["dense", "hybrid_shadow", "hybrid"] = "dense"
    retrieval_expansion_enabled: bool = False
    lexical_degradation_mode: Literal["fail", "dense_only"] = "fail"
    retrieval_fusion_version: str = "weighted_rrf_v1"
    retrieval_rrf_k: int = Field(default=60, gt=0, le=1000)
    retrieval_dense_weight: float = Field(default=1.0, gt=0, le=10)
    retrieval_lexical_weight: float = Field(default=1.0, gt=0, le=10)
    reranking_enabled: bool = False
    reranking_shadow_enabled: bool = False
    reranker_version: str = "none_v1"
    prompt_policy_version: str = "source_only_v1"

    # Pinecone
    pinecone_api_key: str
    pinecone_index_name: str
    pinecone_vector_delete_batch_size: int = Field(default=100, gt=0, le=1000)
    pinecone_vector_delete_timeout_seconds: float = Field(default=5.0, gt=0)
    pinecone_query_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    pinecone_vector_delete_max_attempts: int = Field(default=3, gt=0, le=10)

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

    @field_validator(
        "document_parser_version",
        "ingestion_tokenizer_version",
        "chunk_strategy_version",
        "embedding_text_version",
        "lexical_index_version",
        "dense_index_version",
        "retrieval_fusion_version",
        "reranker_version",
        "prompt_policy_version",
    )
    @classmethod
    def validate_version_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Version identifiers must be non-empty strings")
        if len(normalized) > 128:
            raise ValueError("Version identifiers must be at most 128 characters")
        return normalized

    @field_validator("chat_model")
    @classmethod
    def validate_chat_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("CHAT_MODEL must be a non-empty string")
        return normalized

    @field_validator("openrouter_base_url")
    @classmethod
    def validate_openrouter_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("https://", "http://")):
            raise ValueError("OPENROUTER_BASE_URL must be an HTTP(S) URL")
        return normalized

    @field_validator(
        "otel_exporter_otlp_traces_endpoint",
        "otel_exporter_otlp_metrics_endpoint",
        "otel_exporter_otlp_logs_endpoint",
    )
    @classmethod
    def validate_otel_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized:
            return None
        if not normalized.startswith(("https://", "http://")):
            raise ValueError("OTLP exporter endpoints must be HTTP(S) URLs")
        if (urlsplit(normalized).hostname or "").endswith("grafana.net"):
            raise ValueError(
                "Meridian OTLP endpoints must target a private Grafana Alloy collector, "
                "not Grafana Cloud"
            )
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
        forbidden_direct_export_settings = {
            "OTEL_EXPORTER_OTLP_HEADERS": self.forbidden_otlp_headers,
            "OTEL_EXPORTER_OTLP_ENDPOINT": self.forbidden_otlp_endpoint,
            "GRAFANA_CLOUD_OTLP_ENDPOINT": self.forbidden_grafana_cloud_endpoint,
            "GRAFANA_CLOUD_OTLP_AUTHORIZATION": self.forbidden_grafana_cloud_authorization,
        }
        configured_forbidden_settings = [
            key for key, value in forbidden_direct_export_settings.items() if value
        ]
        if configured_forbidden_settings:
            raise ValueError(
                "Grafana Cloud credentials and direct OTLP settings belong to Grafana "
                "Alloy, not Meridian: " + ", ".join(configured_forbidden_settings)
            )
        if self.observability_enabled and (
            not self.otel_exporter_otlp_traces_endpoint
            or not self.otel_exporter_otlp_metrics_endpoint
            or not self.otel_exporter_otlp_logs_endpoint
        ):
            raise ValueError(
                "OBSERVABILITY_ENABLED requires OTEL_EXPORTER_OTLP_TRACES_ENDPOINT "
                "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT, and "
                "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"
            )
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

        available_input_tokens = min(
            self.chat_context_budget_tokens,
            self.chat_context_window_tokens
            - self.chat_max_output_tokens
            - self.chat_safety_reserve_tokens,
        )
        if available_input_tokens <= 0:
            raise ValueError(
                "Chat context window must leave positive input capacity after output and safety reserves"
            )
        if self.chat_source_min_tokens > self.chat_source_max_tokens:
            raise ValueError(
                "CHAT_SOURCE_MIN_TOKENS must not exceed CHAT_SOURCE_MAX_TOKENS"
            )
        if self.chat_source_min_tokens > available_input_tokens:
            raise ValueError(
                "CHAT_SOURCE_MIN_TOKENS exceeds available chat input capacity"
            )
        if self.chunk_child_target_tokens > self.chunk_child_max_tokens:
            raise ValueError(
                "CHUNK_CHILD_TARGET_TOKENS must not exceed CHUNK_CHILD_MAX_TOKENS"
            )
        if self.chunk_child_overlap_tokens >= self.chunk_child_max_tokens:
            raise ValueError(
                "CHUNK_CHILD_OVERLAP_TOKENS must be below CHUNK_CHILD_MAX_TOKENS"
            )
        if self.chunk_parent_target_tokens > self.chunk_parent_max_tokens:
            raise ValueError(
                "CHUNK_PARENT_TARGET_TOKENS must not exceed CHUNK_PARENT_MAX_TOKENS"
            )
        if (
            self.retrieval_mode == "hybrid"
            and self.lexical_degradation_mode == "dense_only"
        ):
            # Explicit degradation is permitted in live hybrid mode, but callers
            # must opt into it with this named setting rather than silently falling
            # back as a side effect of a dependency error.
            pass
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
