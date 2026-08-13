"""Secret-safe structured operational events for Meridian services.

This module deliberately keeps telemetry vendor-neutral.  Operators can ship the
standard Python log stream to their chosen platform without changing lifecycle
code or exposing prompts, document content, vectors, or credentials.
"""

import json
import logging
import re
import threading
import time
from typing import Any

from opentelemetry import _logs, metrics, trace
from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.context import get_current
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import Status, StatusCode

SAFE_PROVIDER_FAILURES = {
    "authentication",
    "configuration",
    "rate_limited",
    "timeout",
    "unavailable",
    "validation",
    "unknown",
}

_LOG_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__)
PROHIBITED_TELEMETRY_FIELD_PARTS = (
    "authorization",
    "token",
    "secret",
    "password",
    "api_key",
    "prompt",
    "content",
    "vector",
    "embedding",
    "source_text",
    "query",
    "filename",
    "derived_context",
    "raw_payload",
)
PROHIBITED_TELEMETRY_FIELD_NAMES = {
    "document_id",
    "generation_id",
    "job_id",
    "user_id",
    "collection_id",
    "raw_value",
    "error_message",
    "provider_response",
}
APPROVED_TELEMETRY_ATTRIBUTE_KEYS = {
    "attempts",
    "child_count",
    "count",
    "degraded",
    "dense_count",
    "dequeue_timeout_seconds",
    "dependency",
    "duration_ms",
    "clarification_required",
    "deduplicated",
    "element_count",
    "enqueue_job",
    "environment",
    "error_type",
    "failure_class",
    "max_attempts",
    "method",
    "mode",
    "outcome",
    "parent_count",
    "parser_provider",
    "path",
    "request_id",
    "required_permission",
    "retrieved_count",
    "route",
    "scope_mode",
    "scope_version",
    "selected_count",
    "included_count",
    "history_count",
    "source_token_count",
    "history_token_count",
    "summary_token_count",
    "stage",
    "status_class",
    "status_code",
    "status",
    "strategy_version",
    "trace_id",
}

# Exported application events are an interface, not free-form log messages.
# Keep every event name and field set reviewable so a caller cannot accidentally
# turn a customer value into a telemetry attribute.
EVENT_ATTRIBUTE_SCHEMA: dict[str, frozenset[str]] = {
    "api_starting": frozenset({"environment"}),
    "api_clients_initialized": frozenset(),
    "api_stopped": frozenset(),
    "request_completed": frozenset(
        {"method", "route", "status_code", "duration_ms", "outcome"}
    ),
    "unhandled_exception": frozenset({"outcome", "failure_class", "error_type"}),
    "auth0_token_decode_failed": frozenset({"outcome", "failure_class", "error_type"}),
    "auth0_permission_denied": frozenset({"outcome", "required_permission"}),
    "rate_limit_dependency_unavailable": frozenset(
        {"route", "failure_class", "outcome"}
    ),
    "rate_limit_exceeded": frozenset({"route", "outcome"}),
    "chat_context_selected": frozenset(
        {
            "retrieved_count",
            "included_count",
            "history_count",
            "source_token_count",
            "history_token_count",
            "summary_token_count",
            "clarification_required",
            "scope_mode",
            "scope_version",
            "outcome",
        }
    ),
    "chat_retrieval_completed": frozenset(
        {"retrieved_count", "included_count", "scope_mode", "scope_version", "outcome"}
    ),
    "chat_generation_completed": frozenset({"scope_mode", "scope_version", "outcome"}),
    "document_upload_accepted": frozenset({"deduplicated", "enqueue_job", "outcome"}),
    "ingestion_queue_enqueue_failed": frozenset(
        {"outcome", "failure_class", "error_type"}
    ),
    "ingestion_lifecycle_fenced": frozenset({"outcome", "failure_class"}),
    "ingestion_queue_unavailable_using_database_fallback": frozenset(
        {"outcome", "failure_class", "error_type"}
    ),
    "ingestion_worker_recovered_stuck_jobs": frozenset({"count", "outcome"}),
    "ingestion_queue_invalid_job_id": frozenset(
        {"outcome", "failure_class", "error_type"}
    ),
    "ingestion_retry_queue_unavailable": frozenset(
        {"outcome", "failure_class", "error_type"}
    ),
    "ingestion_worker_unexpected_failure": frozenset(
        {"outcome", "failure_class", "error_type"}
    ),
    "embedding_provider_retry_exhausted": frozenset(
        {"outcome", "failure_class", "error_type", "attempts"}
    ),
    "vector_upsert_retry_exhausted": frozenset(
        {"outcome", "failure_class", "error_type", "attempts"}
    ),
    "processing_ingestion_job": frozenset({"attempts", "count", "outcome"}),
    "ingestion_queue_startup_unavailable_using_database_fallback": frozenset(
        {"outcome", "failure_class", "error_type"}
    ),
    "ingestion_worker_started": frozenset(
        {"dequeue_timeout_seconds", "max_attempts", "outcome"}
    ),
    "ingestion_queue_close_failed": frozenset(
        {"outcome", "failure_class", "error_type"}
    ),
    "purge_worker_recovered_stuck_jobs": frozenset({"count", "outcome"}),
    "purge_job_retryable": frozenset(
        {"count", "attempts", "failure_class", "error_type", "outcome"}
    ),
    "purge_job_terminal_failed": frozenset(
        {"count", "attempts", "failure_class", "error_type", "outcome"}
    ),
    "purge_job_complete": frozenset({"count", "attempts", "outcome"}),
    "unclassified_event": frozenset(),
}

APPLICATION_FAILURE_CLASSES = frozenset(
    {
        "authentication",
        "configuration",
        "database",
        "generation",
        "pinecone",
        "redis",
        "validation",
        "rate_limited",
        "timeout",
        "unavailable",
        "lifecycle_fence",
        "unknown",
    }
)
SAFE_ERROR_TYPES = frozenset(
    {
        "AuthenticationError",
        "ConfigurationError",
        "ConnectionError",
        "DatabaseError",
        "JWTError",
        "PineconeException",
        "ProgrammingError",
        "RedisError",
        "TimeoutError",
        "ValueError",
    }
)

RETRIEVAL_OPERATIONAL_THRESHOLDS = {
    "lexical_timeout_rate": 0.02,
    "hybrid_degradation_rate": 0.01,
    "parser_failure_rate": 0.02,
    "activation_failure_rate": 0.01,
    "retrieval_empty_rate_change": 0.10,
    "p95_latency_regression": 0.30,
}

# Stages are metric labels and must stay a fixed, reviewable vocabulary.  Keep
# ingestion and chat completion in the same family as retrieval so operators
# can compare the end-to-end RAG path without admitting caller-provided labels.
RAG_STAGE_VOCABULARY = frozenset(
    {
        "parsing",
        "chunking",
        "embedding",
        "indexing",
        "activation",
        "dense",
        "lexical",
        "fusion",
        "lifecycle_hydration",
        "expansion",
        "reranking",
        "evidence_selection",
        "sse_completion",
        "unknown",
    }
)
RAG_STAGE_OUTCOMES = frozenset(
    {
        "success",
        "failure",
        "validation_failure",
        "degraded",
        "insufficient_context",
        "generation_failure",
        "empty_response",
        "unknown",
    }
)

_meter = metrics.get_meter("meridian.retrieval")
_ingestion_generations = _meter.create_counter("meridian.ingestion.generations")
_ingestion_elements = _meter.create_histogram("meridian.ingestion.elements")
_ingestion_children = _meter.create_histogram("meridian.ingestion.children")
_ingestion_parents = _meter.create_histogram("meridian.ingestion.parents")
_ingestion_child_tokens = _meter.create_histogram("meridian.ingestion.child_tokens")
_ingestion_child_overlap_tokens = _meter.create_histogram(
    "meridian.ingestion.child_overlap_tokens"
)
_retrieval_requests = _meter.create_counter("meridian.retrieval.requests")
_retrieval_candidates = _meter.create_histogram("meridian.retrieval.candidates")
_retrieval_latency = _meter.create_histogram("meridian.retrieval.latency_ms")
_http_requests = _meter.create_counter("meridian.http.requests")
_http_latency = _meter.create_histogram("meridian.http.server.duration_ms")
_worker_heartbeats = _meter.create_counter("meridian.worker.heartbeats")
_worker_jobs = _meter.create_counter("meridian.worker.jobs")
_worker_queue_age = _meter.create_histogram("meridian.worker.queue_age_ms")
_rag_stage_latency = _meter.create_histogram("meridian.rag.stage.duration_ms")
_rag_stage_operations = _meter.create_counter("meridian.rag.stage.operations")
_dependency_operations = _meter.create_counter("meridian.dependency.operations")
_dependency_latency = _meter.create_histogram("meridian.dependency.duration_ms")
_database_pool_connections = _meter.create_histogram(
    "meridian.database.pool.connections"
)

_INGESTION_FAILURE_CLASSES = {
    "parser",
    "activation",
    "embedding",
    "indexing",
    "unknown",
}
_bootstrap_lock = threading.Lock()
_observability_initialized = False
_logger_provider: LoggerProvider | None = None
_otlp_event_logger: Any | None = None
_SAFE_EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


def configure_application_logging(log_level: str) -> None:
    """Configure the shared local JSON logger without attaching an OTLP handler."""
    handler = logging.StreamHandler()
    handler.setFormatter(SecretSafeJsonFormatter())
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        handlers=[handler],
        force=True,
    )


def is_prohibited_telemetry_field(key: str) -> bool:
    """Return whether a field could identify or expose customer data."""
    normalized = key.casefold()
    return normalized in PROHIBITED_TELEMETRY_FIELD_NAMES or any(
        part in normalized for part in PROHIBITED_TELEMETRY_FIELD_PARTS
    )


def sanitize_telemetry_attributes(fields: dict[str, Any]) -> dict[str, Any]:
    """Keep only explicit, bounded attributes safe for external telemetry."""
    return {
        key: value
        for key, value in fields.items()
        if key in APPROVED_TELEMETRY_ATTRIBUTE_KEYS
        and not is_prohibited_telemetry_field(key)
        and (value is None or isinstance(value, (str, int, float, bool)))
        and (not isinstance(value, str) or len(value) <= 128)
    }


def _safe_failure_class(value: Any) -> str:
    return value if value in APPLICATION_FAILURE_CLASSES else "unknown"


def _safe_error_type(value: Any) -> str:
    return value if value in SAFE_ERROR_TYPES else "unknown"


def sanitize_event_attributes(
    event: str, fields: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Normalize a cataloged event and retain only its approved safe fields."""
    safe_event = event if event in EVENT_ATTRIBUTE_SCHEMA else "unclassified_event"
    allowed = EVENT_ATTRIBUTE_SCHEMA[safe_event]
    safe_fields = sanitize_telemetry_attributes(fields)
    result: dict[str, Any] = {}
    for key, value in safe_fields.items():
        if key not in allowed:
            continue
        if key == "failure_class":
            result[key] = _safe_failure_class(value)
        elif key == "error_type":
            result[key] = _safe_error_type(value)
        else:
            result[key] = value
    return safe_event, result


def classify_application_failure(exc: Exception) -> str:
    """Classify an exception without preserving its message or payload."""
    type_name = type(exc).__name__.casefold()
    module_name = type(exc).__module__.casefold()
    if isinstance(exc, ValueError) or "validation" in type_name:
        return "validation"
    if "jwt" in type_name or "auth" in type_name or "permission" in type_name:
        return "authentication"
    if "redis" in type_name or "redis" in module_name:
        return "redis"
    if "pinecone" in type_name or "pinecone" in module_name:
        return "pinecone"
    if (
        "database" in type_name
        or "sqlalchemy" in module_name
        or "asyncpg" in module_name
    ):
        return "database"
    if "configuration" in type_name or "settings" in type_name:
        return "configuration"
    if "generation" in type_name or "openai" in module_name:
        return "generation"
    return "unknown"


def initialize_observability(settings: Any) -> None:
    """Configure OTLP exporters for the internal collector when enabled.

    Grafana Alloy, rather than Meridian, owns Grafana Cloud credentials. Application
    attributes deliberately contain only bounded operational labels.
    """
    global _logger_provider, _observability_initialized, _otlp_event_logger
    if not settings.observability_enabled:
        return
    with _bootstrap_lock:
        if _observability_initialized:
            return
        resource = Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment.name": settings.environment,
            }
        )
        trace_provider = TracerProvider(
            resource=resource,
            sampler=TraceIdRatioBased(settings.otel_trace_sample_ratio),
        )
        trace_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=settings.otel_exporter_otlp_traces_endpoint,
                )
            )
        )
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(
                endpoint=settings.otel_exporter_otlp_metrics_endpoint,
            )
        )
        metrics.set_meter_provider(
            MeterProvider(resource=resource, metric_readers=[metric_reader])
        )
        trace.set_tracer_provider(trace_provider)
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(endpoint=settings.otel_exporter_otlp_logs_endpoint),
                max_queue_size=2048,
                max_export_batch_size=512,
                schedule_delay_millis=1000,
                export_timeout_millis=5000,
            )
        )
        _logs.set_logger_provider(logger_provider)
        _logger_provider = logger_provider
        _otlp_event_logger = logger_provider.get_logger("meridian.events")
        _observability_initialized = True


def shutdown_observability() -> None:
    """Flush telemetry without allowing a collector outage to stop serving."""
    global _logger_provider, _otlp_event_logger
    if _logger_provider is None:
        return
    try:
        _logger_provider.force_flush(timeout_millis=5000)
        _logger_provider.shutdown()
    except Exception:
        logging.getLogger(__name__).warning("otlp_log_shutdown_failed")
    finally:
        _logger_provider = None
        _otlp_event_logger = None


def _otlp_severity(level: int) -> SeverityNumber:
    if level >= logging.CRITICAL:
        return SeverityNumber.FATAL
    if level >= logging.ERROR:
        return SeverityNumber.ERROR
    if level >= logging.WARNING:
        return SeverityNumber.WARN
    if level >= logging.INFO:
        return SeverityNumber.INFO
    return SeverityNumber.DEBUG


def _safe_otlp_event_name(event: str) -> str:
    return event if _SAFE_EVENT_NAME_PATTERN.fullmatch(event) else "unclassified_event"


def emit_safe_otlp_log(
    event: str,
    *,
    level: int = logging.INFO,
    fields: dict[str, Any] | None = None,
    otlp_logger: Any | None = None,
) -> None:
    """Export one allowlisted event without serializing a Python log record.

    The optional logger makes the boundary directly testable.  Export failures are
    deliberately fail-open: telemetry must never alter API readiness or worker work.
    """
    destination = otlp_logger if otlp_logger is not None else _otlp_event_logger
    if destination is None:
        return
    safe_event, attributes = sanitize_event_attributes(event, fields or {})
    try:
        destination.emit(
            LogRecord(
                timestamp=time.time_ns(),
                observed_timestamp=time.time_ns(),
                context=get_current(),
                severity_number=_otlp_severity(level),
                severity_text=logging.getLevelName(level),
                body=safe_event,
                attributes=attributes,
                event_name=safe_event,
            )
        )
    except Exception:
        logging.getLogger(__name__).warning("otlp_log_export_failed")


def _join_route_template(prefix: str, path_format: str) -> str:
    joined = f"{prefix.rstrip('/')}{path_format or ''}"
    if not joined:
        return "/"
    return joined if joined.startswith("/") else f"/{joined}"


def build_route_template_registry(routes: list[Any]) -> dict[Any, str]:
    """Map matched endpoint callables to full registered API templates.

    FastAPI's included-router scope route is intentionally local to the child
    router, so this registry is built once after all routers are registered.
    """
    registry: dict[Any, str] = {}
    for route in routes:
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        if original_router is not None and include_context is not None:
            prefix = str(getattr(include_context, "prefix", ""))
            for child_route in getattr(original_router, "routes", []):
                endpoint = getattr(child_route, "endpoint", None)
                path_format = getattr(child_route, "path_format", None)
                if endpoint is not None and path_format is not None:
                    registry[endpoint] = _join_route_template(prefix, path_format)
            continue
        endpoint = getattr(route, "endpoint", None)
        path_format = getattr(route, "path_format", None)
        if endpoint is not None and path_format is not None:
            registry[endpoint] = _join_route_template("", path_format)
    return registry


def resolve_route_template(scope: dict[str, Any], registry: dict[Any, str]) -> str:
    """Resolve only a known route template; raw URL paths are never a fallback."""
    return registry.get(scope.get("endpoint"), "unmatched")


def current_trace_id() -> str | None:
    """Return a correlation identifier without recording request data."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.trace_id:032x}"


def current_span_id() -> str | None:
    """Return the active span correlation identifier without customer data."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.span_id:016x}"


def record_http_observation(
    *, method: str, route: str, status_code: int, duration_ms: float
) -> None:
    """Record RED metrics using only method, route template, and status class."""
    attributes = {
        "method": method,
        "route": route,
        "status_class": f"{status_code // 100}xx",
    }
    _http_requests.add(1, attributes)
    _http_latency.record(duration_ms, attributes)


def record_worker_heartbeat(*, worker: str, outcome: str = "running") -> None:
    """Record liveness for a long-running worker with a bounded worker label."""
    _worker_heartbeats.add(1, {"stage": worker, "outcome": outcome})


def record_worker_job_observation(
    *,
    worker: str,
    operation: str,
    outcome: str,
    queue_age_ms: float | None = None,
    failure_class: str | None = None,
) -> None:
    """Record a bounded worker state transition without job or owner identifiers."""
    attributes = {"stage": f"{worker}.{operation}", "outcome": outcome}
    if failure_class:
        attributes["failure_class"] = failure_class
    _worker_jobs.add(1, attributes)
    if queue_age_ms is not None:
        _worker_queue_age.record(max(queue_age_ms, 0), {"stage": worker})


def record_rag_stage_observation(
    *, stage: str, outcome: str, duration_ms: float, degraded: bool = False
) -> None:
    """Record a bounded RAG stage in both metrics and the active trace."""
    attributes = {
        "stage": normalize_rag_stage(stage),
        "outcome": normalize_rag_stage_outcome(outcome),
        "degraded": degraded,
    }
    _rag_stage_operations.add(1, attributes)
    safe_duration_ms = max(duration_ms, 0)
    _rag_stage_latency.record(safe_duration_ms, attributes)
    trace.get_current_span().add_event(
        "rag.stage", {**attributes, "duration_ms": safe_duration_ms}
    )


def normalize_rag_stage(stage: str) -> str:
    """Return a bounded RAG-stage metric label for an internal stage name."""
    return stage if stage in RAG_STAGE_VOCABULARY else "unknown"


def normalize_rag_stage_outcome(outcome: str) -> str:
    """Return a bounded RAG-stage outcome label."""
    return outcome if outcome in RAG_STAGE_OUTCOMES else "unknown"


def record_dependency_observation(
    *, dependency: str, outcome: str, duration_ms: float
) -> None:
    """Record bounded dependency availability and latency observations."""
    attributes = {"dependency": dependency, "outcome": outcome}
    _dependency_operations.add(1, attributes)
    _dependency_latency.record(duration_ms, attributes)


def record_database_pool_observation(engine: Any) -> None:
    """Sample bounded SQLAlchemy pool capacity without emitting connection IDs."""
    pool = getattr(getattr(engine, "sync_engine", engine), "pool", None)
    if pool is None and all(
        callable(getattr(engine, method_name, None))
        for method_name in ("size", "checkedout", "overflow")
    ):
        pool = engine
    if pool is None:
        return
    for state, method_name in (
        ("size", "size"),
        ("checked_out", "checkedout"),
        ("overflow", "overflow"),
    ):
        method = getattr(pool, method_name, None)
        if not callable(method):
            continue
        try:
            _database_pool_connections.record(max(int(method()), 0), {"state": state})
        except Exception:
            # Pool introspection is operational telemetry only and must fail open.
            continue


class DependencySpan:
    """Time one dependency call and emit a safe child span and metric."""

    def __init__(self, dependency: str, operation: str) -> None:
        self.dependency = dependency
        self.operation = operation
        self._started = 0.0
        self._context_manager = trace.get_tracer(
            "meridian.dependencies"
        ).start_as_current_span(f"{dependency}.{operation}")
        self._span = None

    def __enter__(self) -> "DependencySpan":
        self._started = time.perf_counter()
        self._span = self._context_manager.__enter__()
        self._span.set_attribute("dependency", self.dependency)
        self._span.set_attribute("stage", self.operation)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        duration_ms = round((time.perf_counter() - self._started) * 1000, 2)
        outcome = "success" if exc is None else "failure"
        assert self._span is not None
        self._span.set_attribute("outcome", outcome)
        if exc is not None:
            self._span.set_status(Status(StatusCode.ERROR))
        self._context_manager.__exit__(exc_type, exc, traceback)
        record_dependency_observation(
            dependency=self.dependency, outcome=outcome, duration_ms=duration_ms
        )
        return False


def record_ingestion_prepared(
    *,
    parser_provider: str,
    strategy_version: str,
    element_count: int,
    child_count: int,
    parent_count: int,
    child_token_total: int,
    child_overlap_tokens: int,
) -> None:
    """Record bounded structured-ingestion observations without document data."""
    attributes = {
        "parser_provider": parser_provider,
        "strategy_version": strategy_version,
    }
    _ingestion_generations.add(1, {**attributes, "outcome": "prepared"})
    _ingestion_elements.record(element_count, attributes)
    _ingestion_children.record(child_count, attributes)
    _ingestion_parents.record(parent_count, attributes)
    _ingestion_child_tokens.record(child_token_total, attributes)
    _ingestion_child_overlap_tokens.record(max(child_overlap_tokens, 0), attributes)


def record_ingestion_outcome(
    *,
    outcome: str,
    strategy_version: str,
    failure_class: str | None = None,
) -> None:
    """Record a bounded terminal or failure outcome for one generation."""
    if failure_class is not None and failure_class not in _INGESTION_FAILURE_CLASSES:
        failure_class = "unknown"
    attributes: dict[str, str] = {
        "outcome": outcome,
        "strategy_version": strategy_version,
    }
    if failure_class is not None:
        attributes["failure_class"] = failure_class
    _ingestion_generations.add(1, attributes)


def record_retrieval_observation(
    *,
    mode: str,
    dense_count: int,
    lexical_count: int,
    fusion_overlap: int,
    selected_count: int,
    lifecycle_excluded_count: int,
    expansion_added_count: int,
    reranking_count: int,
    qualifying_count: int,
    degraded: bool,
    total_latency_ms: float,
) -> None:
    """Record bounded candidate counts and end-to-end retrieval latency."""
    attributes = {"mode": mode, "degraded": degraded}
    _retrieval_requests.add(1, attributes)
    for channel, value in {
        "dense": dense_count,
        "lexical": lexical_count,
        "fusion_overlap": fusion_overlap,
        "selected": selected_count,
        "lifecycle_excluded": lifecycle_excluded_count,
        "expansion_added": expansion_added_count,
        "reranking": reranking_count,
        "qualifying": qualifying_count,
    }.items():
        _retrieval_candidates.record(value, {**attributes, "channel": channel})
    _retrieval_latency.record(total_latency_ms, attributes)


class SecretSafeJsonFormatter(logging.Formatter):
    """Serialize standard log records without accidental payload/credential fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        trace_id = current_trace_id()
        span_id = current_span_id()
        if trace_id:
            payload["trace_id"] = trace_id
        if span_id:
            payload["span_id"] = span_id
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            if key not in APPROVED_TELEMETRY_ATTRIBUTE_KEYS:
                continue
            if is_prohibited_telemetry_field(key):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, default=str, sort_keys=True)


def classify_provider_failure(exc: Exception) -> str:
    """Return a bounded, credential-safe provider failure category."""
    status_code = getattr(exc, "status_code", None)
    if status_code in {401, 403}:
        return "authentication"
    if status_code == 429:
        return "rate_limited"
    if isinstance(status_code, int) and 500 <= status_code <= 599:
        return "unavailable"

    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "timeout"
    if "auth" in name or "permission" in name:
        return "authentication"
    if "validation" in name or isinstance(exc, ValueError):
        return "validation"
    if "connection" in name or "unavailable" in name:
        return "unavailable"
    return "unknown"


def lifecycle_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit a cataloged event to local JSON and the safe OTLP bridge."""
    safe_event, safe_fields = sanitize_event_attributes(event, fields)
    local_fields = dict(safe_fields)
    request_id = fields.get("request_id")
    if isinstance(request_id, str) and len(request_id) <= 128:
        # Support correlation is intentionally local-only. OTLP receives trace
        # context instead and never indexes this unbounded client value.
        local_fields["request_id"] = request_id
    logger.log(level, safe_event, extra=local_fields)
    emit_safe_otlp_log(safe_event, level=level, fields=safe_fields)


def retrieval_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit bounded retrieval-stage counts and latencies without user content."""
    lifecycle_event(logger, event, **fields)
