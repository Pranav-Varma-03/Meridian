# Milestone 1 Manual Test Cases (Supabase + Redis + Pinecone)

Run these after filling `.env` and applying migrations.

## Pre-check
1. `make setup`
2. `make db-migrate`
3. `make dev-api`

Expected: API starts without startup exceptions.

---

## Test 1: Root endpoint
- Request: `GET http://localhost:8000/`
- Expect:
  - `200 OK`
  - JSON includes `message` and `version`

## Test 2: Health endpoint healthy path
- Request: `GET http://localhost:8000/health`
- Expect:
  - `200 OK`
  - JSON keys: `api`, `redis`, `database`, `status`, `timestamp`
  - `status` is `healthy` if Redis + DB are reachable

## Test 3: Correlation ID behavior
- Request with custom header `x-request-id: test-123`
- Endpoint: `/health`
- Expect response header includes same `x-request-id: test-123`

## Test 4: Validation error format
- Request invalid payload to `POST /api/v1/chat` with body `{}`
- Expect:
  - `422`
  - body format:
    - `error.code = "VALIDATION_ERROR"`
    - `error.request_id` present
    - `error.details.errors` present

## Test 5: HTTP exception format
- Request `GET /api/v1/documents/non-existent-id`
- Expect:
  - `404`
  - body format:
    - `error.code = "HTTP_ERROR"`
    - `error.request_id` present

## Test 6: Migration tables exist (Supabase SQL editor)
Verify tables exist:
- `users`
- `collections`
- `documents`
- `document_chunks`
- `ingestion_jobs`
- `conversations`
- `messages`

---

## Quick curl snippets

```bash
curl -i http://localhost:8000/
curl -i http://localhost:8000/health
curl -i -H "x-request-id: test-123" http://localhost:8000/health
curl -i -X POST http://localhost:8000/api/v1/chat -H "content-type: application/json" -d '{}'
curl -i http://localhost:8000/api/v1/documents/non-existent-id
```
