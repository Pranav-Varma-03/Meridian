# Grafana observability manual test guide

## Prerequisites

1. Start the API, ingestion worker, purge worker, and the directly installed,
   private Grafana Alloy host service. Use the deployment secret manager for all
   `GRAFANA_CLOUD_*` values.
2. Set `OBSERVABILITY_ENABLED=true` for every Meridian process and point its
   OTLP trace/metric/log endpoints at Alloy (`http://127.0.0.1:4318/v1/...`).
   Alloy's separate health/debug endpoint is `http://127.0.0.1:12345` and is
   not an OTLP destination. Do not set `OTEL_EXPORTER_OTLP_HEADERS`,
   `OTEL_EXPORTER_OTLP_ENDPOINT`, or any `GRAFANA_CLOUD_*` value in Meridian's
   `.env`; those values belong only to Alloy's host-service environment.
3. Open API Swagger at `http://localhost:8000/docs` and authenticate using the
   existing Swagger/Auth0 workflow. Open the Meridian Grafana folder separately.

## Swagger-first verification

1. Use `GET /health`; expect `200` with healthy dependency status. Confirm an
   API request metric and a route-template trace, with no request body/headers.
   In Loki query `{service_name="meridian-api"}` and confirm the safe
   `request_completed` event has trace correlation but no request ID.
2. Use `GET /api/v1/documents?limit=10&offset=0` through Swagger/BFF (an
   unauthenticated request may return `401`). In Mimir, confirm the
   `meridian_http_requests_total` route label is `/api/v1/documents`, not an
   empty string, UUID, or query string.
3. Use the document upload endpoint with the disposable evaluation fixture;
   expect its documented success response. Confirm an ingestion heartbeat,
   queue-age observation, and completion or bounded failure-class metric.
4. Use the chat endpoint with an evaluation question; expect its documented SSE
   response. Confirm dense/lexical, lifecycle-hydration, and evidence-selection
   observations without the question, citation text, document id, or filename.
5. In Grafana, open the persisted **Meridian operational overview** and confirm API RED,
   worker, dependency, and RAG-stage panels receive series.

## Negative checks

1. Call a protected Swagger endpoint without authorization; expect its existing
   `401` response and an API `4xx` class metric only.
2. Submit invalid endpoint input; expect the documented `422` response. Verify
   validation details do not appear in exported logs, metrics, or trace attrs.
3. Temporarily stop Alloy in non-production. API health and a normal request
   must still complete; Alloy health/export failure must be visible locally and
   no telemetry secret or customer content may be emitted.

## Completion checklist

- [ ] API, ingestion, and purge telemetry reach the intended Grafana Cloud stack.
- [ ] Dashboard panels and alert routing were verified with a controlled failure.
- [ ] Trace/log correlation is present, without prohibited fields or request IDs.
- [ ] Synthetic API and worker-heartbeat monitors pass from the target region.
- [ ] Baseline SLO thresholds and on-call destinations have explicit owners.
