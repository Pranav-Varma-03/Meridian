# Meridian API Contract Reference

This is the developer-facing contract for Meridian's current `/api/v1` API. Swagger
at `http://localhost:8000/docs` is the interactive source for the same request and
response schemas; this guide explains flows, lifecycle semantics, and SSE behavior
that are awkward to infer from an individual endpoint.

## Prerequisites and shared rules

Start the supported local topology from `Meridian/`:

```bash
make db-migrate
make dev-api
make dev-worker
make dev-web
```

All `/api/v1` routes require an Auth0 API access token unless stated otherwise. In
Swagger, click **Authorize** and paste the raw JWT. In HTTP clients send:

```http
Authorization: Bearer <auth0-access-token>
```

The token audience must equal `AUTH0_AUDIENCE`. `POST /api/v1/ingest` additionally
requires the `documents:reingest` permission. Every API response includes
`X-Request-ID`; clients can supply one with `X-Request-ID` for correlation.

For local Swagger authentication, configure the root `.env` with the Auth0 web
application values (`AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, and
`AUTH0_SECRET`) plus the Auth0 API identifier as `AUTH0_AUDIENCE`. In Auth0, the
web application's callback URL must be `http://localhost:3000/auth/callback`; its
API must use that same identifier, have RBAC enabled, and add permissions to access
tokens. Sign in at `http://localhost:3000`, obtain that API access token from the
authenticated web session, then paste the JWT (without `Bearer`) into Swagger's
**Authorize** dialog. Log out and in again after changing audience or permissions.

Errors use this envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "details": {}
  }
}
```

Common codes are `HTTP_ERROR`, `VALIDATION_ERROR`, `INTERNAL_SERVER_ERROR`,
`RATE_LIMITED`, and `RATE_LIMIT_DEPENDENCY_UNAVAILABLE`.

## Health and diagnostics

| Endpoint | Auth | Success | Notes |
|---|---|---:|---|
| `GET /` | No | 200 | API name and version. |
| `GET /health` | No | 200 | Backward-compatible API/Redis/Postgres status; may report `degraded`. |
| `GET /health/live` | No | 200 | Process liveness only; does not probe dependencies. |
| `GET /health/ready` | No | 200 / 503 | Checks Postgres, Redis, Pinecone index access, and OpenRouter configuration. |
| `GET /api/v1/auth/token-claims` | Yes | 200 / 404 | Development only; returns allowlisted verified claims. |
| `POST /api/v1/users/me` | Yes | 200 | Ensures the local user record exists and returns it. |

Example token diagnostics response:

```json
{
  "iss": "https://your-tenant.us.auth0.com/",
  "aud": "https://api.meridian.local",
  "permissions": ["documents:reingest"]
}
```

## Collections

All collection routes are owner-scoped. List routes accept `limit` (1–100) and
`offset` (0+), and return `{ "collections": [...], "total": 1 }`.

| Endpoint | Request | Success | Important failures |
|---|---|---:|---|
| `POST /api/v1/collections` | `{ "name": "Product Docs", "description": "..." }` | 201 | 409 duplicate name; 422 invalid name. |
| `GET /api/v1/collections` | Query pagination | 200 | 401 unauthenticated. |
| `GET /api/v1/collections/{collection_id}` | UUID path | 200 | 404 owner-scoped missing collection. |
| `PATCH /api/v1/collections/{collection_id}` | At least one of `name`, `description` | 200 | 400 empty update; 409 duplicate name. |
| `DELETE /api/v1/collections/{collection_id}` | UUID path | 200 | 404 missing collection. |

Deleting a collection **does not delete documents**. The database changes their
`collection_id` to `null`, so they remain active, owner-scoped, and searchable through
an `all` chat scope.

## Documents and ingestion jobs

| Endpoint | Request | Success | Important failures |
|---|---|---:|---|
| `POST /api/v1/documents/upload` | Multipart `file`; optional `collection_id` query UUID | 202 / 200 | 413 >10 MiB; 415 unsupported type; 429; 503 rate-limit coordination unavailable. |
| `GET /api/v1/documents` | Optional `collection_id`, `limit`, `offset` | 200 | 404 unknown collection. |
| `GET /api/v1/documents/{document_id}` | UUID path | 200 | 404 missing/deleted/not-owned document. |
| `DELETE /api/v1/documents/{document_id}` | UUID path | 200 | 404 missing/not-owned document. |
| `GET /api/v1/ingest/{job_id}` | UUID path | 200 | 404 missing/not-owned job. |

Supported upload types: PDF, DOCX, and TXT. `collection_id` belongs in the URL, for
example:

```bash
curl -X POST 'http://localhost:8000/api/v1/documents/upload?collection_id=7ecff269-f648-4601-8d97-1c6f0fabf906' \
  -H 'Authorization: Bearer <token>' \
  -F 'file=@handbook.pdf;type=application/pdf'
```

Upload returns `202` when work is queued. It can return `200` for identical bytes
already owned by the user, with `deduplicated: true` and
`reused_existing_job: true`. Poll the returned `job_id` until its status reaches
`ready` or `failed`; do not treat `202` as provider completion.

Document deletion returns:

```json
{ "message": "Document deleted and cleanup queued" }
```

It immediately excludes the document from Meridian reads and retrieval. A durable
purge worker later removes raw storage and Pinecone vectors; provider convergence is
asynchronous and does not make the document visible again.

### Explicit re-ingestion

`POST /api/v1/ingest` creates a new generation for an existing owned document:

```json
{
  "document_id": "9f4f8cce-b7b4-4a0a-b529-4f6f5906d5e4",
  "reason": "model_migration"
}
```

Allowed reasons are `manual_repair`, `model_migration`, and `chunking_change`.
The route requires `documents:reingest`, returns `202`, and returns the existing job
when an equivalent active job already exists. The active old generation stays
retrievable until a new generation is safely active; stale vectors are purged later.

Uploads and explicit re-ingestion share one per-user ingestion bucket. Defaults are
10 requests per 3,600 seconds. `429 RATE_LIMITED` includes `Retry-After`; if Redis
cannot coordinate the limit, both routes return `503
RATE_LIMIT_DEPENDENCY_UNAVAILABLE` before creating work.

## Grounded chat and conversations

`POST /api/v1/chat` is authenticated **POST-SSE**. It returns
`text/event-stream`, not a JSON answer. Request fields:

- `query`: required, 1–12,000 characters.
- `conversation_id`: optional UUID. Omit to create a conversation.
- `retrieval_scope`: preferred scope object.
- `collection_ids`: legacy compatibility field; new clients must use
  `retrieval_scope`.

Start with all active user documents:

```json
{
  "query": "Summarize the onboarding policy",
  "retrieval_scope": { "mode": "all" }
}
```

Restrict retrieval to selected user-owned collections:

```json
{
  "query": "What is the retention policy?",
  "retrieval_scope": {
    "mode": "collections",
    "collection_ids": ["7ecff269-f648-4601-8d97-1c6f0fabf906"]
  }
}
```

Continue a conversation without changing its saved scope by sending only
`conversation_id` and `query`. To change it, include a new `retrieval_scope`; the
change is persisted with a version and the first affected user-message sequence.
`mode: "all"` requires an empty collection list; `mode: "collections"` requires at
least one unique user-owned collection. Supplying conflicting legacy and new scope
fields returns 422.

The stream emits zero or more `text` events, exactly one `sources` event, then one
terminal `done` event:

```text
data: {"type":"text","content":"The policy ..."}

data: {"type":"sources","content":[{"document_id":"...","generation":2}]}

data: {"type":"done","conversation_id":"...","retrieval_scope":{"mode":"all","collection_ids":[],"version":1}}
```

If no lifecycle-valid evidence can fit, the stream returns Meridian's grounded
insufficiency answer with an empty `sources` event. A generation failure after the
stream begins produces an SSE `error` followed by `done`; partial assistant content is
not saved as a completed conversation message.

| Endpoint | Success | Notes |
|---|---:|---|
| `GET /api/v1/chat/conversations` | 200 | Paginated owner-scoped list with current retrieval scope. |
| `GET /api/v1/chat/conversations/{conversation_id}` | 200 | Messages, citations, current scope, and scope-event history. |
| `DELETE /api/v1/chat/conversations/{conversation_id}` | 200 | Deletes owner-scoped conversation and its messages. |

Chat is limited to 20 requests per 60 seconds per authenticated user by default. A
`429 RATE_LIMITED` response happens before retrieval/generation; Redis outage returns
`503 RATE_LIMIT_DEPENDENCY_UNAVAILABLE` rather than failing open.

## Swagger completion checklist

- [ ] Authorize with a valid Auth0 API token.
- [ ] Verify `/health/live` and `/health/ready`.
- [ ] Create/list/update/delete a collection and confirm associated documents become
  unfiled rather than deleted.
- [ ] Upload a disposable document, poll its ingestion job to `ready`, and retrieve it.
- [ ] Test `POST /api/v1/chat` with `all` and `collections` scopes; inspect `sources`
  and `done` events.
- [ ] Re-ingest with a permitted token and an allowed reason; poll the new job.
- [ ] Delete the disposable document and confirm it immediately disappears from
  Meridian reads before provider cleanup converges.
- [ ] Verify 401, 403, 404, 422, 429, and Redis-degradation 503 negative cases.

## Verification record

Automated verification completed on 2026-07-29:

- `apps/api/.venv/bin/ruff check apps/api/app apps/api/tests` — passed.
- `apps/api/.venv/bin/pytest -q apps/api/tests` — passed (136 tests).
- `pnpm --dir apps/web lint`, `typecheck`, and `build` — passed. The build reports
  two pre-existing shell warnings from malformed non-secret text in the root `.env`
  (lines 16 and 94); it still exits successfully and this change does not alter it.

Swagger verification remains a developer-run checklist because it requires a live
local Auth0 session and configured Postgres, Redis, Pinecone, and generation provider.
Record the date and result here when completing the checklist above.
