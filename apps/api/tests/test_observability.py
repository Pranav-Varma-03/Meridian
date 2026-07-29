import json
import logging

from app.core.observability import SecretSafeJsonFormatter, classify_provider_failure


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
        }
    )

    payload = json.loads(SecretSafeJsonFormatter().format(record))

    assert payload["event"] == "chat_retrieval_completed"
    assert payload["request_id"] == "request-1"
    assert "authorization" not in payload
    assert "source_text" not in payload
    assert "vector_count" not in payload


def test_provider_failure_classification_is_bounded() -> None:
    error = RuntimeError("unexpected")

    assert classify_provider_failure(error) == "unknown"
