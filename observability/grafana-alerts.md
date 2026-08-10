# Meridian Grafana Cloud alert specification

Create a Grafana Cloud folder named `Meridian` and configure the alert rules
below using Mimir/Prometheus queries. Route warning alerts to the engineering
channel and critical alerts through Grafana OnCall or the team's escalation
policy. Do not add user, document, query, filename, or request-id labels.

Grafana Cloud converts OpenTelemetry dots and dashes in metric names to
underscores. The metrics below therefore use the Prometheus-compatible names.

| Alert | PromQL expression | Condition | Severity | First response |
| --- | --- | --- | --- | --- |
| Lexical timeout/degradation | `sum(rate(meridian_retrieval_requests_total{mode="hybrid",degraded="true"}[10m])) / clamp_min(sum(rate(meridian_retrieval_requests_total{mode="hybrid"}[10m])), 1)` | > 0.02 for 10m | Warning | Inspect PostgreSQL saturation and query plans; use dense-only degradation or rollback. |
| Hybrid degradation | `sum(rate(meridian_retrieval_requests_total{mode=~"hybrid|hybrid_shadow",degraded="true"}[10m])) / clamp_min(sum(rate(meridian_retrieval_requests_total{mode=~"hybrid|hybrid_shadow"}[10m])), 1)` | > 0.01 for 10m | Warning | Inspect lexical dependency failures and traces. |
| Parser failure rate | `sum(rate(meridian_ingestion_generations_total{outcome="failed",failure_class="parser"}[15m])) / clamp_min(sum(rate(meridian_ingestion_generations_total[15m])), 1)` | > 0.02 for 15m | Warning | Check parser release, unsupported file types, and worker logs. |
| Activation failure rate | `sum(rate(meridian_ingestion_generations_total{outcome="failed",failure_class="activation"}[10m])) / clamp_min(sum(rate(meridian_ingestion_generations_total[10m])), 1)` | > 0.01 for 10m | Critical | Halt rollout; inspect vector manifests and generation fencing. |
| Retrieval-empty shift | `sum(rate(meridian_retrieval_candidates_count{channel="qualifying"}[30m]))` | Relative decrease >10% from approved baseline | Warning | Check active generations, collection filters, lexical state, and retrieval mode. |
| Retrieval p95 regression | `histogram_quantile(0.95, sum by (le) (rate(meridian_retrieval_latency_ms_bucket[15m])))` | >30% above approved baseline | Warning | Inspect PostgreSQL/Pinecone latency; disable expansion/reranking or roll back mode. |

Before enabling notifications, set the two relative baselines from the
representative-corpus load test, attach a dashboard and rollback runbook to
every rule, and configure evaluation intervals to match the table.

Also configure:

1. A Grafana Cloud synthetic/uptime monitor for public `/health`, expecting HTTP
   200.
2. A worker heartbeat alert when no successful worker heartbeat occurs within
   five minutes.

Tag alert rules with `service=meridian-api`, environment, owner, and severity
so escalation policies route incidents correctly.
