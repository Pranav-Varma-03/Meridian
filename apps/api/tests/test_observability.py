import json
import logging

from app.core.observability import (
    APPROVED_TELEMETRY_ATTRIBUTE_KEYS,
    RETRIEVAL_OPERATIONAL_THRESHOLDS,
    SecretSafeJsonFormatter,
    classify_provider_failure,
    record_ingestion_outcome,
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
