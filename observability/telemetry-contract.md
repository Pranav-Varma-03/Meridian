# Meridian telemetry contract v1

## Signal ownership

| Signal | Instrumentation | Collection | Destination | Owner |
| --- | --- | --- | --- | --- |
| Metrics | OpenTelemetry Metrics | Grafana Alloy | Grafana Mimir | Platform engineering |
| Traces | OpenTelemetry Tracing | Grafana Alloy | Grafana Tempo | Platform engineering |
| Logs | Secret-safe JSON stdout | Grafana Alloy | Grafana Loki | Platform engineering |

## Approved attributes

Only bounded values may be exported: service/environment/deployment identity,
route template, HTTP method and status class, operation/stage, dependency,
outcome, safe failure class, retrieval mode, strategy/configuration version,
counts, attempts, and duration. `request_id` is local log correlation only and
MUST NOT become a metric label or resource attribute.

## Prohibited data

Never export user, document, collection, generation, or job IDs; filenames;
queries; raw request/response bodies; source/embedding/derived text; prompts;
vectors; provider payloads; credentials; authorization headers; secrets; or
unbounded free-text attributes. HTTP body and header capture is disabled.

## Cardinality rules

Metric labels are limited to bounded enumerations and route templates. Never
use identifiers, trace/request IDs, hashes, timestamps, filenames, URLs with
IDs, or arbitrary exception messages as labels. New attributes require a
contract test and an active-series cost review.

## Required coverage

API RED metrics, worker heartbeats and queue health, dependency health, and RAG
parse/chunk/embed/index/activate/retrieve/generate stages must emit safe counts,
latency, outcomes, and failure classes. Collector export health is monitored
separately and MUST NOT affect application serving readiness.
