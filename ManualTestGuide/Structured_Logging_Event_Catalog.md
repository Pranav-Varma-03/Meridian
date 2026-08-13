# Structured logging event catalog

Meridian application logs are a reviewed interface. Use `lifecycle_event()` for
application lifecycle, security, RAG, ingestion, and purge events. It emits the
same safe event to local JSON logs and, when enabled, the OTLP log bridge.

## Safety rules

- Event names are constants from `EVENT_ATTRIBUTE_SCHEMA` in
  `apps/api/app/core/observability.py`. Unknown names become
  `unclassified_event` with no attributes.
- Each event can emit only its documented attributes. Unrecognised attributes,
  IDs, filenames, prompts, document text, bearer tokens, credentials, vectors,
  and raw error messages are dropped.
- `request_id` is retained only in the local JSON record for support
  correlation. It is deliberately not exported to OTLP/Loki.
- `failure_class` and `error_type` are bounded vocabularies. Classify an
  exception with `classify_application_failure(exc)`; do not send `str(exc)`.

## Event families

| Family | Events and trigger | Severity | Permitted attributes |
|---|---|---|---|
| API | `api_starting`, `api_clients_initialized`, `api_stopped` at process lifecycle; `request_completed` after every response; `unhandled_exception` for a safe 500 | INFO; ERROR for unhandled failure | Environment; HTTP method/route/status/duration/outcome; bounded failure class/type |
| Auth and limits | Token validation, denied permission, rate-limit dependency/flood condition | WARNING | Outcome, required permission, safe route, bounded failure class/type |
| Chat | Context selected, retrieval complete, generation complete | INFO | Counts, token-budget counts, clarification flag, scope mode/version, outcome |
| Upload and ingestion | Upload accepted, queue failure/fallback, lifecycle fence, recovery, retry, ready | INFO; WARNING/ERROR for failure | Deduplication/queue state, counts, attempts, bounded failure class/type, outcome |
| Purge | Stuck-job recovery, retry, terminal failure, complete | INFO; WARNING for retry/failure | Count, attempts, bounded failure class/type, outcome |

All families prohibit the same sensitive values: bearer tokens, credentials,
claims, request bodies, queries/prompts, document text, filenames, vectors,
durable identifiers, raw queue values, raw provider payloads, and raw exception
messages. Local JSON can include `request_id`; the OTLP bridge always omits it.

## Adding an event

1. Add a constant event name and its exact safe field set to
   `EVENT_ATTRIBUTE_SCHEMA`.
2. Add an event-focused unit test for allowed attributes and rejected
   customer-controlled fields.
3. Call `lifecycle_event`, using bounded values only:

```python
lifecycle_event(
    logger,
    "purge_job_retryable",
    level=logging.WARNING,
    count=42,
    attempts=2,
    outcome="retryable",
    failure_class=classify_application_failure(exc),
    error_type=type(exc).__name__,
)
```

4. Add the event to this catalog and update the Grafana runbook if it changes
   an operator workflow.

Never bypass the catalog with a raw `logger.exception(...)` on a request,
document, provider, or worker path.
