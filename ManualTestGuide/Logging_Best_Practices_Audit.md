# Meridian logging best-practices audit

## Bottom line

Meridian has a strong logging foundation: structured JSON, stable event names, allowlisted fields, OTLP correlation, and collector-side defense-in-depth. That is much better than typical “print an exception and hope” logging.

The event-contract and diagnostic gaps identified in this audit were remediated
in August 2026. Meridian validates application events against an explicit event
catalog, emits safe bounded diagnostic fields for unexpected failures, and
routes the core auth/chat/ingestion/purge lifecycle paths through that catalog.
Raw bearer-token stdout output remains temporarily enabled at the requester's
direction for local debugging and must be removed before shared, staging, or
production use. See
[Structured logging event catalog](Structured_Logging_Event_Catalog.md).

## Credential-exposure cleanup

If the old debug output handled a real bearer token, stop and restart the API
processes so no stale process keeps printing it. Treat any retained terminal,
CI, container, or collector output as access-controlled incident data under the
normal retention policy. Revoke the affected Auth0 session/token or rotate the
credential only when a real token may have been retained outside its intended
restricted environment; no rotation is needed for a known synthetic test token.

## What good application logging looks like

A production log should answer:

> What happened, where, when, how severe, what safe outcome/decision occurred, and how can I correlate it with the rest of the request?

A good event is structured, stable, and intentionally designed:

```json
{
  "timestamp": "2026-08-12T10:15:31.248Z",
  "level": "INFO",
  "event": "document_ingestion_completed",
  "trace_id": "…",
  "service": "meridian-api",
  "environment": "staging",
  "outcome": "success",
  "parser_provider": "unstructured",
  "child_count": 18,
  "duration_ms": 714.2
}
```

It should not be a prose dump such as:

```text
Uploaded handbook.pdf for user 892... using token eyJ... content: ...
```

The structured form is searchable, dashboard-friendly, and safer.

OpenTelemetry models this with timestamp, severity, body/event name, resource attributes, optional trace/span context, and structured attributes. Event names should identify one stable event structure and must not contain dynamic values. [OpenTelemetry log data model](https://opentelemetry.io/docs/specs/otel/logs/data-model/), [OpenTelemetry event conventions](https://opentelemetry.io/docs/specs/semconv/general/events/)

## The useful mental model: logs, metrics, and traces

```text
                  One customer request / worker job
                              │
      ┌───────────────────────┼────────────────────────┐
      ▼                       ▼                        ▼
    Logs                    Metrics                  Traces
 “why did it fail?”   “is it getting worse?”   “where was time spent?”
 event + safe facts   aggregate counts/latency  operation causality
```

For Meridian:

- **Logs**: `document_upload_accepted`, `purge_job_retryable`, `auth0_permission_denied`.
- **Metrics**: request rate, queue age, retrieval latency, lifecycle exclusions, error ratios.
- **Traces**: API request → Redis → Postgres → Pinecone → LLM flow.

Do not use logs as a metric store. Logging every chunk, token, embedding, prompt, or candidate will be expensive and dangerous. Keep individual events for meaningful state transitions, decisions, and failures.

## Meridian: current implementation compared with best practice

| Area | Current Meridian behavior | Assessment |
|---|---|---|
| Structured format | JSON output via `SecretSafeJsonFormatter` | Good |
| Stable event names | Events such as `request_completed`, `purge_job_complete` | Good |
| Trace correlation | JSON includes active `trace_id`/`span_id`; OTLP passes context | Good |
| Secret/content filtering | Explicit allowlist and prohibited field-name patterns | Very good |
| Collector defense | Alloy removes sensitive attributes again before Grafana export | Very good |
| Bounded telemetry labels | Fixed RAG stage/outcome vocabulary | Good |
| Log exporter failure | OTLP export fails open | Correct |
| Token logging | Temporary raw bearer-token stdout output for local debugging | Deferred — remove before shared/staging/production use |
| Useful log fields | Reviewed context/retrieval counts are cataloged | Remediated |
| Exception diagnostics | Global failures use bounded type/classification | Remediated |
| Worker correlation | Job/document IDs deliberately removed; no alternative correlation | Investigability trade-off |
| Event schema governance | Code-enforced event → allowed-field catalog with developer guide | Remediated |

## What Meridian currently does well

### 1. It protects RAG content unusually well

[`observability.py`](../apps/api/app/core/observability.py) blocks fields related to:

- Authorization tokens, secrets, passwords, API keys
- Prompts, queries, content, source text, embeddings, vectors
- Filenames, document IDs, user IDs, collection IDs, job IDs, generation IDs
- Raw provider payloads and error messages

This is the right default for a PDF/RAG application. User questions, document text, citations, embeddings, and bearer tokens are all sensitive or commercially sensitive. OWASP specifically warns against access tokens, session identifiers, credentials, sensitive personal data, connection strings, and commercially sensitive material in logs. [OWASP guidance](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)

### 2. It has defense in depth

The application sanitizes fields first, then [`config.alloy`](../observability/alloy/config.alloy) removes known dangerous attributes again before export.

That is a good architecture:

```text
Application event
   │
   ├─ allowlist safe attributes
   │
   ▼
stdout JSON + OTLP event
   │
   ├─ collector drops sensitive attributes again
   ├─ collector rejects oversized log bodies
   ▼
Grafana Cloud / Loki
```

A future developer can accidentally add `document_id` to a logger call; the application and collector both attempt to prevent it from reaching the external platform.

### 3. It avoids unbounded metric labels

Meridian’s metrics use bounded fields like `stage`, `outcome`, `mode`, and `status_class`. That aligns with Grafana’s guidance: low-cardinality labels such as service/environment are safe; user IDs, UUIDs, request IDs, and timestamps must not become metric or Loki labels. [Grafana Cloud cardinality guidance](https://grafana.com/docs/grafana-cloud/learn-and-build/telemetry-signals/use-signals-together/key-concepts/), [Loki cardinality documentation](https://grafana.com/docs/loki/latest/get-started/labels/cardinality/)

### 4. It uses a sane event helper

`lifecycle_event(...)` is the right direction:

```python
lifecycle_event(
    logger,
    "document_upload_accepted",
    outcome="success",
)
```

It centralizes field sanitization and sends the same safe event to local JSON logs and OTLP. That is better than letting every router/service invent its own logging structure.

## Remediated issues

### High: useful event fields are now intentionally cataloged

The formatter remains intentionally allowlist-based. The prior chat fields were
renamed into concise, reviewed attributes and added to the event catalog:

```python
"retrieved_source_count"
"included_source_count"
"included_history_count"
"input_budget_tokens"
"source_tokens"
"history_tokens"
"summary_tokens"
"rewrite_requested_clarification"
```

Those counts now allow operators to answer questions such as:

- “Did this request find sources but exclude them due to token budget?”
- “Are users receiving insufficiency because retrieval is empty or because context selection is too restrictive?”
- “Did query rewriting request clarification unusually often?”

The fix was not “allow arbitrary extras.” `EVENT_ATTRIBUTE_SCHEMA` now permits
only a small set of bounded numeric/boolean fields per event; unknown event
names normalize to `unclassified_event` and retain no attributes.

For example:

```python
lifecycle_event(
    logger,
    "chat_retrieval_completed",
    outcome="success",
    retrieved_count=12,
    included_count=4,
    history_count=3,
    source_token_count=1840,
    clarification_required=False,
)
```

These are explicitly approved, documented in the event catalog, and tested.

### High: unexpected exceptions now carry safe diagnostics

The global handler now logs the equivalent of:

```python
lifecycle_event(
    logger,
    "unhandled_exception",
    level=logging.ERROR,
    outcome="failed",
    failure_class=classify_application_failure(exc),
    error_type=type(exc).__name__,
)
```

The exported result preserves safety while making an `ERROR` actionable:

```json
{
  "event": "unhandled_exception",
  "level": "ERROR",
  "error_type": "ProgrammingError",
  "outcome": "failure"
}
```

Do not export raw exception messages by default; database/provider errors may contain URLs, SQL fragments, file paths, or customer input. Use a bounded failure class (`database`, `redis`, `pinecone`, `generation`, `validation`, `unknown`) plus the exception type where safe.

### Medium: core lifecycle calls use the shared event boundary

The audit originally found a mixture of:

```python
logger.warning("...")
logger.exception("...", extra={...})
lifecycle_event(logger, "...")
```

The core auth, request-failure, chat, ingestion, and purge paths now use
`lifecycle_event`. This provides local JSON and OTLP parity and prevents caller
fields from bypassing the catalog. Direct log calls must remain constant,
content-free diagnostics only.

The old approach had drawbacks:

- Useful `extra` fields are silently dropped if not allowlisted.
- OTLP export occurs only through `lifecycle_event`, not ordinary `logger.warning`.
- Some events use human prose; some use machine event names.
- The event schema is not obvious at the call site.

For production behavior, application lifecycle/security/retrieval/worker events should preferentially use the common helper. Ordinary debug diagnostics can use regular loggers, but they should still use constant messages and vetted fields.

Python’s standard approach supports passing contextual fields through `extra`; Meridian is correctly using that mechanism, but it needs a documented schema and consistent wrapper use. [Python logging cookbook](https://docs.python.org/3.10/howto/logging-cookbook.html)

### Medium: request correlation needs a clear policy

Meridian includes `request_id` in local JSON but removes it from OTLP events. That is a defensible privacy choice because request IDs can be user-provided and unbounded. But then developers need a standard correlation path:

- Use `trace_id` / `span_id` for cross-service and Grafana correlation.
- Return `X-Request-ID` to the client for support correlation.
- Keep request ID in restricted local/API logs only if necessary.
- Never make request ID a Loki label or metric label.

This matches Grafana’s warning that request IDs and UUIDs should not be labels. [Grafana Cloud guidance](https://grafana.com/docs/grafana-cloud/learn-and-build/telemetry-signals/use-signals-together/key-concepts/)

## Recommended logging rules for Meridian developers

### Log these

| Event type | Examples | Level |
|---|---|---|
| Lifecycle transition | worker started, job activated, purge complete | `INFO` |
| State change | generation moved from pending to active | `INFO` |
| Safe business/security denial | permission denied, rate limit exceeded | `WARNING` |
| Recoverable dependency fault | Redis unavailable with DB fallback | `WARNING` |
| Failed operation requiring action | retry exhausted, activation failure | `ERROR` |
| Fatal process condition | unrecoverable startup failure | `CRITICAL` |

### Do not log these

- Raw JWTs, API keys, cookies, `Authorization` headers
- User query text or conversation history
- Document text, excerpts, source chunks, filenames
- Embeddings, vectors, raw provider requests/responses
- Raw database exceptions or SQL
- User/document/job/collection/generation IDs in external telemetry
- Dynamic event names, route instances containing UUIDs, or free-form metric labels

### Prefer this pattern

```python
lifecycle_event(
    logger,
    "ingestion_activation_failed",
    level=logging.ERROR,
    outcome="failure",
    failure_class="activation",
    error_type=type(exc).__name__,
    attempts=attempt,
)
```

Not this:

```python
logger.exception(
    f"Failed to activate generation {generation_id} for {filename}: {exc}"
)
```

The first is searchable, safe, bounded, and suitable for alerts. The second exposes identifiers and possibly source/provider details.

## Recommended log event contract

Meridian would benefit from a short internal event catalog:

```text
event: ingestion_activation_failed
severity: ERROR
when: generation activation cannot complete after validation
required attributes:
  outcome: "failure"
  failure_class: "activation"
optional attributes:
  error_type: bounded exception class
  attempts: integer
prohibited:
  document_id, generation_id, job_id, filename, source text, provider message
```

This follows OpenTelemetry’s event principle: one stable event name maps to one well-defined event structure. [OpenTelemetry event conventions](https://opentelemetry.io/docs/specs/semconv/general/events/)

## Suggested priority order

1. **Immediately remove bearer-token printing** in auth.
2. Add a regression test proving access tokens never appear in stdout/log records/exported telemetry.
3. Standardize important application events through `lifecycle_event`.
4. Define and approve a compact operational field schema for chat, ingestion, purge, auth, and failures.
5. Add safe `error_type` / `failure_class` to unexpected exceptions and terminal worker failures.
6. Publish an event catalog and a developer checklist.
7. Periodically scan for `print(`, f-string logger messages, and raw `logger.exception` calls.
8. Review Loki label configuration: only stable resource labels should be indexed; dynamic fields belong in structured attributes, never labels.

## Current assessment

```text
Security posture          ████████░░  Strong design, blocked by raw JWT print
Structured logging        ████████░░  Good formatter and event helper
Telemetry privacy         █████████░  Allowlist + Alloy defense are excellent
Operational usefulness    ██████░░░░  Important event fields are being dropped
Failure diagnosis         █████░░░░░  Error type/context needs improvement
Consistency               ██████░░░░  Two logging paths need standardization
```

The important distinction: Meridian does not need more logs everywhere. It needs **fewer, more intentional, safer, schema-defined events**—and the raw token print must be removed first.
