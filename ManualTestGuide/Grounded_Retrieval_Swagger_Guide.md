# Grounded retrieval — Swagger manual guide

Use a disposable local or staging tenant only. This guide verifies the structured
child/parent ingestion model, source-only answers, and generation-safe cleanup.

## Prerequisites

1. Apply migrations and start the API plus both workers:

   ```bash
   make db-migrate
   make dev-api
   make dev-worker
   ```

2. Configure Auth0, Postgres, Redis, Pinecone, and OpenRouter in `.env`.
   In `http://localhost:8000/docs`, authorize with an Auth0 API access token.
   The re-ingestion test additionally needs `documents:reingest`.
3. Keep `RETRIEVAL_MODE=dense` for the baseline. Use only a disposable tenant
   for `hybrid_shadow` or `hybrid`; PostgreSQL lexical retrieval is not BM25.

## Upload and verify grounded answers

1. Upload two disposable files using `POST /api/v1/documents/upload`. Include an
   exact identifier such as `TRV-104` in the first file and a distinct identifier
   in the second. Expect `202` and a document/job identifier for each.
2. Wait until each document's latest job is `ready`. A new structured generation
   has child rows, parent windows, lexical state, vectors, and a manifest before
   it can become active.
3. Call `POST /api/v1/chat` with a paraphrased fact from the first file. Expect
   `200 text/event-stream`, one `sources` event, then `done`. Each source must
   reference the active generation and may include parent, supporting-child,
   section-path, and page-range provenance.
4. Ask the exact `TRV-104` question. In a disposable `hybrid_shadow` validation,
   inspect logs/metrics for lexical/fusion activity while the user-visible answer
   remains dense-compatible. Do not enable `hybrid` until evaluation gates pass.
5. Ask a fact absent from both files. Expect the deterministic insufficiency
   answer, an empty `sources` event, and no general-knowledge answer.
6. Upload two sources with contradictory statements and ask about the conflict.
   Expect the answer to report the conflict with citations rather than select an
   unsupported resolution.

## Re-ingestion and two-document smoke test

1. Re-ingest only the first document using `POST /api/v1/ingest` with
   `reason: "chunking_change"`. Expect `202`; the previous generation remains
   queryable until the new one activates.
2. After the new job is ready, query the first document again. Its sources must
   cite only the new active generation. Historic conversation citations remain
   immutable snapshots and are never silently rewritten.
3. Delete the first document with `DELETE /api/v1/documents/{document_id}`.
   It must disappear from reads and retrieval immediately; the purge worker then
   removes only that document's vectors, lexical state, and stored content.
4. Query the second document's distinct identifier. It must remain retrievable
   throughout the first document's re-ingestion and deletion cleanup.

## Negative cases and completion checklist

- Omit authorization: expect `401` on protected routes.
- Use an unowned collection in a chat scope: expect the documented `404`/`422`.
- Re-ingest without `documents:reingest`: expect `403`; use an unsupported reason:
  expect `422`.
- Stop the lexical dependency only in non-production: `hybrid` follows
  `LEXICAL_DEGRADATION_MODE` (`dense_only` or safe failure) and never answers from
  general knowledge.

- [ ] Semantic and exact-identifier answers have active-generation citations.
- [ ] Unsupported and conflicting evidence follow source-only policy.
- [ ] Re-ingestion activates exactly one new generation.
- [ ] Deleting one document preserves the other document's dense and lexical state.
