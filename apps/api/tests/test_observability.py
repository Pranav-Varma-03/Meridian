import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from app import main as main_module
from app.core import observability
from app.core.observability import (
    APPROVED_TELEMETRY_ATTRIBUTE_KEYS,
    RETRIEVAL_OPERATIONAL_THRESHOLDS,
    SecretSafeJsonFormatter,
    classify_provider_failure,
    normalize_rag_stage,
    normalize_rag_stage_outcome,
    record_database_pool_observation,
    record_ingestion_outcome,
    record_ingestion_prepared,
    record_rag_stage_observation,
    record_retrieval_observation,
    record_worker_job_observation,
    sanitize_telemetry_attributes,
)


def test_structured_logs_exclude_sensitive_fields() -> None:
    record = logging.makeLogRecord(
        {
            "msg": "chat_retrieval_completed",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "name": "test",
            "request_id": "request-1",
            "authorization": "Bearer should-not-appear",
            "source_text": "should-not-appear",
            "vector_count": 10,
            "document_id": "document-canary-should-not-appear",
            "query": "query-canary-should-not-appear",
            "filename": "filename-canary-should-not-appear",
        }
    )

    payload = json.loads(SecretSafeJsonFormatter().format(record))

    assert payload["event"] == "chat_retrieval_completed"
    assert payload["request_id"] == "request-1"
    assert "authorization" not in payload
    assert "source_text" not in payload
    assert "vector_count" not in payload
    assert "document_id" not in payload
    assert "query" not in payload
    assert "filename" not in payload


def test_telemetry_attributes_allow_only_bounded_safe_schema() -> None:
    attributes = sanitize_telemetry_attributes(
        {
            "mode": "hybrid",
            "status_code": 200,
            "document_id": "document-canary-should-not-appear",
            "query": "query-canary-should-not-appear",
            "filename": "filename-canary-should-not-appear",
            "unknown_key": "unknown-canary-should-not-appear",
        }
    )

    assert attributes == {"mode": "hybrid", "status_code": 200}
    assert "document_id" not in APPROVED_TELEMETRY_ATTRIBUTE_KEYS


def test_provider_failure_classification_is_bounded() -> None:
    error = RuntimeError("unexpected")

    assert classify_provider_failure(error) == "unknown"


def test_operational_thresholds_are_bounded_and_content_free() -> None:
    assert RETRIEVAL_OPERATIONAL_THRESHOLDS["lexical_timeout_rate"] == 0.02
    assert all(
        "text" not in key and "prompt" not in key
        for key in RETRIEVAL_OPERATIONAL_THRESHOLDS
    )


def test_retrieval_observations_accept_only_bounded_operational_values() -> None:
    record_retrieval_observation(
        mode="hybrid_shadow",
        dense_count=12,
        lexical_count=8,
        fusion_overlap=4,
        selected_count=16,
        lifecycle_excluded_count=3,
        expansion_added_count=2,
        reranking_count=5,
        qualifying_count=6,
        degraded=False,
        total_latency_ms=42.5,
    )


def test_ingestion_outcomes_bound_unknown_failure_classes() -> None:
    record_ingestion_outcome(
        outcome="failed",
        strategy_version="structure_aware_parent_child_v1",
        failure_class="untrusted-provider-message",
    )


def test_worker_and_rag_observations_use_bounded_operational_labels() -> None:
    record_worker_job_observation(
        worker="ingestion",
        operation="activation",
        outcome="complete",
        queue_age_ms=12.5,
    )
    record_rag_stage_observation(
        stage="lifecycle_hydration", outcome="success", duration_ms=8.4
    )


def test_rag_stage_observations_bound_unknown_stage_labels() -> None:
    """Free-form stage names must not create unbounded metric series."""
    assert normalize_rag_stage("document-canary-should-not-be-a-label") == "unknown"
    assert (
        normalize_rag_stage_outcome("document-canary-should-not-be-a-label")
        == "unknown"
    )
    record_rag_stage_observation(
        stage="document-canary-should-not-be-a-label",
        outcome="success",
        duration_ms=1.0,
    )


def test_rag_stage_observation_adds_a_correlated_trace_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, dict[str, object]]] = []

    class _Span:
        def add_event(self, name: str, attributes: dict[str, object]) -> None:
            events.append((name, attributes))

    class _Metric:
        def add(self, *_args, **_kwargs) -> None:
            return None

        def record(self, *_args, **_kwargs) -> None:
            return None

    monkeypatch.setattr(
        observability.trace, "get_current_span", lambda *_args, **_kwargs: _Span()
    )
    monkeypatch.setattr(observability, "_rag_stage_operations", _Metric())
    monkeypatch.setattr(observability, "_rag_stage_latency", _Metric())

    record_rag_stage_observation(stage="dense", outcome="success", duration_ms=12.5)

    assert events == [
        (
            "rag.stage",
            {
                "stage": "dense",
                "outcome": "success",
                "degraded": False,
                "duration_ms": 12.5,
            },
        )
    ]


def test_ingestion_prepared_records_overlap_and_token_distribution_inputs() -> None:
    record_ingestion_prepared(
        parser_provider="local",
        strategy_version="structure_aware_parent_child_v1",
        element_count=3,
        child_count=8,
        parent_count=2,
        child_token_total=900,
        child_overlap_tokens=48,
    )


def test_database_pool_sampling_uses_only_bounded_state_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[tuple[int, dict[str, str]]] = []

    class _Metric:
        def record(self, value: int, attributes: dict[str, str]) -> None:
            observations.append((value, attributes))

    class _Pool:
        def size(self) -> int:
            return 5

        def checkedout(self) -> int:
            return 2

        def overflow(self) -> int:
            return 0

    monkeypatch.setattr(observability, "_database_pool_connections", _Metric())
    record_database_pool_observation(_Pool())

    assert observations == [
        (5, {"state": "size"}),
        (2, {"state": "checked_out"}),
        (0, {"state": "overflow"}),
    ]


def test_otlp_log_bridge_exports_only_allowlisted_attributes() -> None:
    class CapturingOtelLogger:
        def __init__(self) -> None:
            self.records = []

        def emit(self, record) -> None:
            self.records.append(record)

    assert hasattr(observability, "emit_safe_otlp_log")
    destination = CapturingOtelLogger()
    observability.emit_safe_otlp_log(
        "chat_completed",
        level=logging.INFO,
        fields={
            "status_code": 200,
            "request_id": "request-canary-must-not-export",
            "document_id": "document-canary-must-not-export",
            "query": "query-canary-must-not-export",
            "unknown_extra": "unknown-canary-must-not-export",
            "error_message": "exception-canary-must-not-export",
        },
        otlp_logger=destination,
    )

    assert len(destination.records) == 1
    record = destination.records[0]
    assert record.body == "chat_completed"
    assert record.attributes == {"status_code": 200}
    serialized = f"{record.body} {record.attributes}"
    assert "canary-must-not-export" not in serialized


def test_otlp_log_bridge_fails_open_when_exporter_raises() -> None:
    class FailingOtelLogger:
        def emit(self, record) -> None:
            raise RuntimeError("collector failure")

    assert hasattr(observability, "emit_safe_otlp_log")
    observability.emit_safe_otlp_log(
        "ingestion_completed",
        fields={"outcome": "success"},
        otlp_logger=FailingOtelLogger(),
    )


def test_canonical_route_registry_uses_full_included_router_templates() -> None:
    def list_documents() -> None:
        return None

    def get_document() -> None:
        return None

    class ChildRoute:
        def __init__(self, endpoint, path_format: str) -> None:
            self.endpoint = endpoint
            self.path_format = path_format

    class IncludedRoute:
        def __init__(self) -> None:
            self.original_router = type(
                "Router",
                (),
                {
                    "routes": [
                        ChildRoute(list_documents, ""),
                        ChildRoute(get_document, "/{document_id}"),
                    ]
                },
            )()
            self.include_context = type(
                "IncludeContext", (), {"prefix": "/api/v1/documents"}
            )()

    assert hasattr(observability, "build_route_template_registry")
    registry = observability.build_route_template_registry([IncludedRoute()])

    assert registry[list_documents] == "/api/v1/documents"
    assert registry[get_document] == "/api/v1/documents/{document_id}"


@pytest.mark.asyncio
async def test_documents_request_records_the_full_route_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[dict[str, object]] = []
    monkeypatch.setattr(
        main_module,
        "record_http_observation",
        lambda **kwargs: observations.append(kwargs),
    )

    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/documents?limit=10&offset=0")

    assert response.status_code == 401
    assert observations == [
        {
            "method": "GET",
            "route": "/api/v1/documents",
            "status_code": 401,
            "duration_ms": pytest.approx(observations[0]["duration_ms"]),
        }
    ]


@pytest.mark.asyncio
async def test_route_telemetry_uses_parameterized_templates_and_unmatched_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[dict[str, object]] = []
    monkeypatch.setattr(
        main_module,
        "record_http_observation",
        lambda **kwargs: observations.append(kwargs),
    )

    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.get("/api/v1/documents/00000000-0000-0000-0000-000000000001")
        await client.get("/api/v1/collections/00000000-0000-0000-0000-000000000002")
        await client.get("/api/v1/no-such-route?document_id=must-not-be-exported")

    assert [observation["route"] for observation in observations] == [
        "/api/v1/documents/{document_id}",
        "/api/v1/collections/{collection_id}",
        "unmatched",
    ]
