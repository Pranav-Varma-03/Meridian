# Initial Retrieval Activation Gates

This document defines the gates for the first `structure_aware_parent_child_v1`
and hybrid-retrieval activation. It uses the disposable dense-only baseline in
`dense_512_character_disposable_2026-08-03.md` as the comparison point. New
behavior remains disabled by default (`RETRIEVAL_MODE=dense`) until every
mandatory gate passes on the versioned evaluation fixture and disposable-tenant
verification.

## Mandatory safety gates

| Area | Gate | Required result |
| --- | --- | --- |
| Tenant and collection isolation | Contract, integration, and manual tests | No cross-owner, out-of-scope collection, deleting, or superseded-generation evidence can be hydrated. |
| Evidence provenance | Prompt/citation parity tests | Every cited excerpt is byte-for-byte sourced from active Postgres evidence; generated context, vector metadata, and scores are excluded. |
| Unsupported questions | Deterministic insufficiency tests | No qualifying source bypasses the generation provider and returns the standard insufficiency response. |
| Activation/purge fencing | Ingestion lifecycle tests | A partial generation never activates; compensation affects only that generation and the previous active generation remains retrievable. |
| Secret safety | Log/telemetry tests and manual inspection | Logs and metrics contain no query, source, embedding, prompt, vector, credential, or raw provider payload. |

Any failure is a release blocker, regardless of aggregate retrieval metrics.

## Retrieval and grounded-answer quality gates

| Metric | Initial threshold | Baseline reference |
| --- | ---: | --- |
| Recall@10 | No regression; target at least +5 percentage points | 8/9 selected-evidence proxy (88.9%) |
| MRR@10 | No regression; target at least +0.03 | 0.889 selected-evidence proxy |
| Context precision@10 | No regression; target at least +0.05 | 0.667 selected-evidence proxy |
| Exact citation correctness | At least 0.90 and no regression on legacy cases | 0.444 strict selected-citation proxy |
| Source-groundedness | At least 0.90 | 0.800 manual review proxy |
| Conflict/insufficiency accuracy | At least 0.95 | 0.900 selected-case proxy |

The baseline proxy did not retrieve full top-36 result sets. Before a production
activation decision, the same runner must produce a full candidate-level baseline
and candidate run; until then these thresholds are canary gates, not release
approval.

## Operational gates

| Area | Gate | Required result |
| --- | --- | --- |
| PostgreSQL lexical load | `EXPLAIN (ANALYZE, BUFFERS)` and representative-owner load test | Owner/generation predicates use the GIN plan; no unbounded sequential scan; statement timeout has no routine hits. |
| Ingestion cost | Per-document provider and storage comparison | Mean cost no more than 25% above dense baseline for the same corpus, excluding one-time migration tooling. |
| Index growth | Vector manifest and parent/child row counts | Vector records grow no more than 2.5x per source document without a documented exception. |
| Prompt cost | Evaluation prompt-token mean | No more than 20% above baseline unless citation correctness improves by at least 10 points. |
| Retrieval p95 latency | End-to-end and stage metrics | No more than 30% above the 24.33 s disposable BFF baseline, and lexical/lifecycle stages each remain under their configured timeout. |

## Rollout decision

1. Keep `dense` as the default after the schema and ingestion implementation lands.
2. Run lexical and fusion in `hybrid_shadow` for a disposable tenant; record the
   full evaluation result, query plan, and secret-safe telemetry.
3. Enable `hybrid` only for a bounded internal canary after every mandatory and
   quality gate passes.
4. Enable expansion and reranking independently; a failed gate reverts the
   relevant feature flag to dense/fused order without a schema rollback.
