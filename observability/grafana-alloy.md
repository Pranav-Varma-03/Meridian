# Meridian Grafana Alloy deployment

Meridian emits vendor-neutral OpenTelemetry metrics, traces, and safe event logs. Run Grafana
Alloy directly as a private host service beside the API and ingestion worker, then forward its OTLP output to
Grafana Cloud. Keep the Grafana Cloud account ID and access-policy token in the
deployment secret manager; never put them in Meridian source code or `.env`.

## Alloy configuration

`observability/alloy/config.alloy` is the sole authoritative collector
configuration. It configures the loopback OTLP receivers, memory limit,
redaction, batching, retry queue, and Grafana Cloud OTLP exporter for metrics,
traces, and logs. Do not copy or maintain a second River configuration here.

Use the exact endpoint and complete Authorization-header value from Grafana
Cloud's **OpenTelemetry** tile, but store both only in Alloy's host-service
environment as `GRAFANA_CLOUD_OTLP_ENDPOINT` and
`GRAFANA_CLOUD_OTLP_AUTHORIZATION`. See `observability/alloy/README.md` for
host-native execution and service setup.

## Meridian workload configuration

Configure both the API and ingestion worker:

```env
OBSERVABILITY_ENABLED=true
OTEL_SERVICE_NAME=meridian-api
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://127.0.0.1:4318/v1/metrics
OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://127.0.0.1:4318/v1/logs
OTEL_TRACE_SAMPLE_RATIO=0.1
```

Use the local Alloy endpoint for the host. The
signal-specific endpoint variables require the full `/v1/traces`,
`/v1/metrics`, and `/v1/logs` paths. Never add `OTEL_EXPORTER_OTLP_HEADERS`,
`OTEL_EXPORTER_OTLP_ENDPOINT`, or `GRAFANA_CLOUD_*` values to Meridian's
`.env`; the application rejects them at startup.

## Verification

1. Deploy Alloy with the Grafana Cloud credentials and exact endpoint from the
   Grafana Cloud Portal.
2. Restart the Meridian API and ingestion worker with the environment above.
3. Request `/health` and complete a disposable ingestion.
4. Confirm the `meridian-api` service in Grafana Cloud Application
   Observability, Tempo traces, Mimir metrics, and Loki logs. In Loki, query
   `{service_name="meridian-api"}` and use the emitted trace ID to navigate to
   Tempo.
5. Verify that document content, prompts, queries, vectors, credentials, and
   request IDs do not appear as exported log attributes, metric labels, or span
   attributes.
