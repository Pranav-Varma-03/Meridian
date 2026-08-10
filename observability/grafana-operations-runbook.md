# Meridian Grafana Cloud operations runbook

## Ownership and access

Platform engineering owns Grafana Alloy, dashboards, alert routing, and access
policy administration. Application engineering owns Meridian signal schemas,
RAG dashboards, and runbook accuracy. Production Grafana Cloud access uses
least-privilege roles: Viewer for incident responders, Editor for dashboard and
alert maintainers, and Admin only for platform administrators.

## Secrets and retention

Grafana Cloud access-policy tokens and Alloy TLS material live only in the
deployment secret manager. Rotate tokens at least every 90 days and immediately
after suspected exposure; record the rotation in the platform change log.
Configure telemetry retention to the approved organizational data policy before
production export, then review access and retention quarterly.

## Cost and capacity budgets

Before production, set a monthly telemetry budget and alerts for active metric
series, metric samples, log volume, trace volume, Alloy queue utilization, and
export failures. Review sampled traces and top label values weekly during the
first rollout, then monthly. Reject new unbounded labels.

## Incident procedure

For a collector/export alert, verify Alloy health, queue growth, Grafana Cloud
status, and egress/TLS credentials. Keep Meridian serving; disable telemetry
export only if bounded queues cannot recover. For a privacy alert, stop export,
rotate affected credentials, preserve local evidence under access control, and
open a security incident.

## Deployment ownership

The deployment owner supplies Grafana Cloud region, account ID, access-policy
token, Alloy hosting model, alert contact points, on-call escalation policy, and
approved retention. These values are intentionally not committed to Meridian.
