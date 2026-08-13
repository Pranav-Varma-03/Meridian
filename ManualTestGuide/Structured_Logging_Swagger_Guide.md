# Structured logging Swagger verification

## Prerequisites

1. Start API, Redis, ingestion worker, purge worker, and (when testing export)
   Grafana Alloy.
2. Open `http://localhost:8000/docs` and use the existing Auth0 bearer-token
   workflow for protected endpoints.
3. Watch API stdout JSON logs. For OTLP verification, use the Meridian Grafana
   dashboard and Loki query `{service_name="meridian-api"}`.

## Tests

| Test | Swagger action | Expected API result | Expected logging result |
|---|---|---|---|
| Healthy request | `GET /health` | `200` | `request_completed` with method, templated route, status code, duration, and no request body/headers |
| Permission denial | Call `POST /api/v1/ingest` without `documents:reingest` | `403` | `auth0_permission_denied`, outcome `denied`; no token or user ID |
| Invalid token | Call any protected endpoint with an invalid bearer token | `401` | `auth0_token_decode_failed` with bounded failure type/class only |
| Upload accepted | Upload a disposable TXT/PDF | `202` or documented duplicate result | `document_upload_accepted`, then worker lifecycle events; no filename, document ID, job ID, or content |
| Chat request | `POST /api/v1/chat` with a short question | `200` SSE stream | `chat_context_selected`, `chat_retrieval_completed`, and on completion `chat_generation_completed`; only counts/scope/outcome |

Queue-recovery and controlled-500 checks require a disposable local/staging
environment: temporarily make Redis unavailable, upload a disposable document,
then restore Redis and confirm the durable database fallback/recovery event.
Use an existing controlled failure fixture or route only if one is available;
do not manufacture a 500 by corrupting production data. The client response
must stay safe while the local/Grafana event contains only bounded
`failure_class` and `error_type`.

## Negative safety check

Use a distinctive harmless canary in a chat question, for example
`logging-canary-123`. The canary must not appear in API stdout JSON, Loki, or
OTLP log attributes. Do not use real credentials or customer data for this
check.

## Completion checklist

- [ ] Auth, upload, chat, and worker events use stable catalog event names.
- [ ] JSON logs contain only documented attributes.
- [ ] Auth bearer token, query/content, filename, IDs, and raw exceptions do
  not appear in logs.
- [ ] OTLP/Loki shows the same event names without `request_id`.
- [ ] With Alloy stopped only in disposable local/staging, API business paths
  continue while telemetry export fails open; restart Alloy afterward.
