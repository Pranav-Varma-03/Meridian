# Production Hardening — Swagger Manual Guide

Use this guide against a disposable development/staging environment only. It is
Swagger-first and intentionally does not expose service credentials in requests.

## Prerequisites

1. Configure `.env` from `.env.example`, including Auth0, Postgres, Redis,
   Pinecone, OpenRouter, and the rate-limit settings.
2. Apply the reviewed schema before starting workers:

   ```bash
   make db-migrate
   make dev-api
   make dev-worker
   ```

3. Open `http://localhost:8000/docs`, click **Authorize**, and paste a current
   Auth0 access token whose `aud` equals `AUTH0_AUDIENCE`. Re-ingestion additionally
   requires the `documents:reingest` permission and one of the documented reasons.

## Health and readiness

1. Execute `GET /health/live`; expect `200` and `status: healthy` even when an
   external dependency is unavailable.
2. Execute `GET /health/ready`; expect `200` only when `database`, `redis`,
   `pinecone`, and `generation` are all `healthy`. Temporarily remove an API key or
   stop Redis to verify the safe `503` readiness response.
3. Execute legacy `GET /health`; expect `200` with `healthy` or `degraded` for
   backwards-compatible monitoring.

## Upload, chat, re-ingestion, and cleanup

1. Upload two disposable TXT/PDF files through `POST /api/v1/documents/upload`.
   Expect `202`, a `document_id`, and a queued job. Wait for the workers to mark both
   documents ready.
2. Call `POST /api/v1/chat` with a question grounded in the first file. Expect an
   SSE `sources` event followed by `done`; source citations must reference only the
   active generation and selected scope.
3. Call the re-ingestion endpoint for the first document with an allowed reason and
   an Auth0 token containing `documents:reingest`. Expect the new generation to become
   active while the old generation remains excluded from retrieval.
4. Delete the first document. Expect logical deletion immediately; the purge worker
   subsequently removes its Pinecone vectors. Verify the second document remains
   retrievable in the same owner namespace.

## Negative cases

- Omit Authorization: protected endpoints return `401` in the common error envelope.
- Use an unknown/restricted collection: chat returns its documented `404`/`422` error.
- Send more than `CHAT_RATE_LIMIT_REQUESTS` chat requests in one configured window:
  expect `429`, `RATE_LIMITED`, and `Retry-After` before retrieval or generation.
- Stop Redis while limits are enabled: chat/upload returns `503`,
  `RATE_LIMIT_DEPENDENCY_UNAVAILABLE`; it must not fail open.
- Re-ingest without the permission or reason: expect the documented `403`/`422` error.

## Completion checklist

- [ ] Liveness and readiness statuses match the dependency state.
- [ ] Upload → worker → ready → cited SSE answer succeeds.
- [ ] Auth, validation, permission, and rate-limit negative cases return safe envelopes.
- [ ] Re-ingestion activates one generation only.
- [ ] Logical deletion excludes results before asynchronous vector cleanup finishes.
- [ ] Two-document smoke test confirms cleanup preserves unrelated vectors.
