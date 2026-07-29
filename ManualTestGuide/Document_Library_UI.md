# Document Library UI — Swagger-first manual test guide

## Prerequisites

1. Start the API with `make dev-api`, the workers with `make dev-worker`, and the web app with `make dev-web` from `Meridian/`.
2. Sign in at `http://localhost:3000/`. The web BFF forwards the Auth0 access token to the API.
3. For direct Swagger checks, open `http://localhost:8000/docs`, use **Authorize**, and paste an Auth0 access token whose audience is the Meridian API. Re-ingestion also requires `documents:reingest`.

## Upload and lifecycle read model

1. In Swagger, call `POST /api/v1/documents/upload` with a PDF, DOCX, or TXT file no larger than 10 MiB. Optionally set `collection_id` in the query string.
2. Expect `202` with `document_id`, `job_id`, and `status: queued` (or `200` only when a completed duplicate is reused).
3. Call `GET /api/v1/documents` and then `GET /api/v1/documents/{document_id}`.
4. Confirm the document has `latest_job` with `id`, `status`, `attempts`, `error`, `started_at`, `completed_at`, and `generation`.
5. While a worker is active, status should progress through `queued` / `processing` to `ready`; refresh the Documents screen, which polls for a bounded period while an active latest job exists.

## Collections and document UI

1. Call `POST /api/v1/collections`, then upload a document with that collection ID.
2. Open `/documents`, choose the collection, and confirm only its documents appear. Choose **All documents** to return to the unfiltered owner-scoped view.
3. Open `/collections`, create and rename a collection. Delete it and confirm its documents remain active but become unfiled.
4. Delete a document from `/documents` and confirm the UI explains that it is removed immediately while file/vector cleanup is queued.

## Re-ingestion (permission-gated)

1. With a token containing `documents:reingest`, use `POST /api/v1/ingest` and one exact reason: `manual_repair`, `model_migration`, or `chunking_change`.
2. Expect `202` for a new job or a safely reused active job. The Documents screen exposes this action only when the user’s token has the permission.

## Negative checks

- Upload an `.exe` or a file over 10 MiB: expect `415` or `413` respectively.
- Use an unknown collection ID: expect `404`.
- Call any protected endpoint without a bearer token: expect `401`.
- Re-ingest without `documents:reingest`: expect `403`; use any other reason: expect `422`.
- Delete an unknown document: expect `404`.

## Completion checklist

- [ ] Upload progresses to ready and `latest_job` reflects its latest attempt.
- [ ] Collection filtering and unfiling after collection deletion work.
- [ ] Document deletion hides the item and queues cleanup.
- [ ] Re-ingestion is visible and functional only for permitted users.
