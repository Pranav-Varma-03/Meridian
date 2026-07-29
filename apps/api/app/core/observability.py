"""Secret-safe structured operational events for Meridian services.

This module deliberately keeps telemetry vendor-neutral.  Operators can ship the
standard Python log stream to their chosen platform without changing lifecycle
code or exposing prompts, document content, vectors, or credentials.
"""

import json
import logging
from typing import Any

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
_SENSITIVE_FIELD_PARTS = (
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
)


class SecretSafeJsonFormatter(logging.Formatter):
    """Serialize standard log records without accidental payload/credential fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            normalized_key = key.lower()
            if any(part in normalized_key for part in _SENSITIVE_FIELD_PARTS):
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
    """Emit a structured event using only caller-supplied non-sensitive fields."""
    logger.log(level, event, extra=fields)
