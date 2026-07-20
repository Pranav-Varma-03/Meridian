# Meridian

Meridian is a monorepo for a production-oriented RAG application.

It currently includes:

- `apps/web` → Next.js frontend
- `apps/api` → FastAPI backend
- `packages/shared` → shared TypeScript types/contracts

## Current implemented state

The repository is currently set up for:

- Authenticated, user-scoped collections
- Authenticated document upload/list/detail/delete APIs
- Redis-backed ingestion job queue
- Background ingestion worker
- Document parsing + semantic chunk persistence
- Embedding generation through a provider-driven embedding layer
- Pinecone vector upsert per user namespace
- User-scoped document deduplication across collections

Current ingestion flow:

1. User uploads a supported file (`PDF`, `DOCX`, `TXT`)
2. API creates the `documents` row and an `ingestion_jobs` row
3. Job is pushed to Redis (`INGESTION_QUEUE_KEY`)
4. Worker dequeues the job and parses/chunks the document
5. Chunks are semantically split using paragraph/sentence/clause-aware chunking with overlap
6. Optional contextual chunk enrichment can be applied before embedding
7. Vectors are upserted to Pinecone under namespace `user:<user_id>`
8. `vector_id` is persisted on each chunk row
9. Job/document move to `ready` on success, or `failed` on error

## Local setup

### 1) Create environment file

```bash
cp .env.example .env
```

Fill `.env` with your credentials and runtime values.

### 2) Required environment values

At minimum, configure:

- `DATABASE_URL` → Supabase/Postgres connection string (must include `sslmode=require` when required by your provider)
- `REDIS_URL`
- `PINECONE_API_KEY`
- `PINECONE_INDEX_NAME`
- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL`
- Auth values:
  - `AUTH0_DOMAIN`
- `AUTH0_AUDIENCE`
- `AUTH0_SCOPE` (normally `openid profile email`)
  - `AUTH0_CLIENT_ID`
  - `AUTH0_CLIENT_SECRET`
  - `AUTH0_SECRET`
- `APP_BASE_URL`
- `API_BASE_URL` (for web → api server-side calls, e.g. `http://localhost:8000`)

`OPENAI_API_KEY` is optional and required only when `EMBEDDING_PROVIDER=openai`.

The web app reads Auth0 values from the same root `.env` file.
No `.env.local` is required for the current setup.

### 3) Embedding configuration

Embeddings are now provider-driven through environment variables.

Example Pinecone embedding configuration:

```env
EMBEDDING_PROVIDER=pinecone
EMBEDDING_MODEL=llama-text-embed-v2
EMBEDDING_INPUT_TYPE=passage
```

Example OpenAI embedding configuration:

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=<your-openai-api-key>
```

Important note for Pinecone `llama-text-embed-v2`:

- use `EMBEDDING_INPUT_TYPE=passage` for indexing/ingestion
- use `query` later for retrieval-time query embeddings

### 3.1) Contextual chunking options

The ingestion pipeline now supports three chunking/enrichment modes:

1. **Base semantic chunking**
   - paragraph / sentence / clause aware splitting
   - overlap preserved between merged semantic units

2. **Native contextual chunking**
   - enable with:

   ```env
   CONTEXTUAL_EMBEDDING_ENABLED=true
   CONTEXTUAL_CHUNKING_PROVIDER=native
   ```

   This uses document-local leading/trailing context to enrich chunk text before embedding.

3. **LLM contextual chunking**
   - enable with:

   ```env
   CONTEXTUAL_EMBEDDING_ENABLED=true
   CONTEXTUAL_CHUNKING_PROVIDER=openai
   CONTEXTUAL_CHUNKING_MODEL=gpt-4o-mini
   OPENAI_API_KEY=<your-openai-api-key>
   ```

   This asks an LLM to generate a short retrieval-oriented context for each chunk before embedding.

### 4) Auth0 quick setup for local development

Use the official `@auth0/nextjs-auth0` flow.

- `AUTH0_DOMAIN=<your-auth0-tenant-domain>`
- `AUTH0_CLIENT_ID=<your-auth0-client-id>`

Configure in the Auth0 dashboard:

- Allowed Callback URLs: `http://localhost:3000/auth/callback`
- Allowed Logout URLs: `http://localhost:3000`
- Application Type: `Regular Web Application`
- Token Endpoint Authentication Method: `client_secret_post`

Recommended Auth0 block:

```env
APP_BASE_URL=http://localhost:3000
AUTH0_DOMAIN=<your-auth0-tenant-domain>
AUTH0_CLIENT_ID=<your-auth0-client-id>
AUTH0_CLIENT_SECRET=<your-auth0-client-secret>
AUTH0_SECRET=<generate with: openssl rand -hex 32>
AUTH0_AUDIENCE=<your-auth0-api-identifier>
AUTH0_SCOPE=openid profile email
```

Important API token requirements:

- In Auth0, create/configure an API with identifier matching `AUTH0_AUDIENCE`
- Enable RBAC and **Add Permissions in the Access Token** for that API.
- Add the `documents:reingest` API permission to the operator/admin role that may request document re-ingestion.
- Access tokens used by the web app must have:
  - `aud = AUTH0_AUDIENCE`
  - `iss = https://<AUTH0_DOMAIN>/`
- The Next.js Auth0 v4 client explicitly requests this audience. Log out and log
  back in after changing it so the session receives a fresh access token.

After login/signup, the web app calls `POST /api/v1/users/me` with the Auth0 access token.
That endpoint verifies JWT and upserts the user into Postgres.

### Development token-claims diagnostic

`GET /api/v1/auth/token-claims` is available only when `ENVIRONMENT=development`.
It verifies the submitted access token normally and returns only `iss`, `aud`, and
`permissions`; it never returns the raw token or profile claims. The route returns
`404` outside development. Use it through Swagger as described in
`ManualTestGuide/Auth0_API_Permissions_Swagger_Manual_Guide.md`.

### 5) Install dependencies

```bash
make setup
```

### 6) Run database migrations

```bash
make db-migrate
```

## Redis setup for local development

Meridian uses Redis for the ingestion queue.

### Option A: Local Redis

Start Redis locally:

```bash
brew services start redis
```

Or run it directly:

```bash
redis-server --port 6379
```

Verify Redis is reachable:

```bash
redis-cli -h 127.0.0.1 -p 6379 ping
```

Expected response:

```text
PONG
```

If you are developing locally and your configured Upstash hostname does not resolve from your machine, override Redis explicitly when starting the API and worker:

```bash
REDIS_URL=redis://localhost:6379 make dev-api
REDIS_URL=redis://localhost:6379 make dev-worker
```

### Option B: Upstash Redis

Use your Upstash connection string in `.env`:

```env
REDIS_URL=rediss://<redis-username>:<redis-password>@<redis-host>:<redis-port>
```

If Upstash DNS/connectivity is unavailable locally, the API startup health checks and worker startup will fail until Redis is reachable.

## Running the app locally

### Start backend only

```bash
make dev-api
```

### Start frontend only

```bash
make dev-web
```

### Start frontend + backend together

```bash
make dev
```

### Start ingestion worker

Run all background workers in a separate terminal during local ingestion testing:

```bash
make dev-worker
```

The terminal lists the running ingestion and purge workers with their PIDs.
Press `Ctrl+C` once to stop both. Use `make dev-purge-worker` only when you
intentionally need the cleanup worker by itself.

### Start purge worker

Run this separately to remove vectors/files for logically deleted documents and
superseded ingestion generations:

```bash
make dev-purge-worker
```

Direct worker command:

```bash
cd apps/api && .venv/bin/python -m app.services.ingestion_worker_runner
```

If you need to force local Redis:

```bash
cd /Users/pranav/Desktop/RAG/Meridian
REDIS_URL=redis://localhost:6379 make dev-api
REDIS_URL=redis://localhost:6379 make dev-worker
```

Open:

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`

## Implemented APIs

### Collections API

`/api/v1/collections` endpoints are DB-backed and user-scoped:

- `POST /api/v1/collections`
- `GET /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `PATCH /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`

Notes:

- All collection routes require Auth0 bearer-token auth
- Collection names are unique per user (case-insensitive)
- List/detail responses include `document_count`
- Delete returns `200` with `{ "message": "Collection deleted" }`

### Documents + Ingestion APIs

`/api/v1/documents` includes DB-backed, user-scoped metadata endpoints:

- `POST /api/v1/documents/upload`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}`
- `DELETE /api/v1/documents/{document_id}`

`/api/v1/ingest` lifecycle endpoints are also available:

- `POST /api/v1/ingest` → queue ingestion for an existing document
- `GET /api/v1/ingest/{job_id}` → fetch ingestion job status

Notes:

- Upload creates both a `documents` record and an `ingestion_jobs` record in `queued` state
- Upload validations enforce supported MIME types (`PDF`, `DOCX`, `TXT`) and a max size of `10MB`
- Uploaded/manual ingest jobs are pushed to Redis and consumed by the background worker
- All document and ingestion operations are authenticated and scoped to the current user
- Repeated manual ingest calls are idempotent while an active job already exists
- Document deletion removes recorded Pinecone vector IDs from the document owner’s
  namespace before deleting the database record. If Pinecone is temporarily
  unavailable, deletion returns `503` and leaves the document intact so it can be
  retried safely.

### Current deduplication behavior

Document deduplication is now **user-scoped**, not collection-scoped.

That means:

- collections behave like tags/organization buckets
- identical file uploads for the same user deduplicate even if `collection_id` differs
- the same bytes uploaded again by the same user reuse the existing document/job response instead of creating duplicate document content

## Swagger/OpenAPI manual testing

Swagger UI is the expected manual verification path for API work.

Open:

- `http://localhost:8000/docs`

Relevant manual guides in this repo:

- `ManualTestGuide/Documents_Ingestion_Swagger_Manual_Guide.md`
- `ManualTestGuide/CollectionTesting_Manual_Guide.md`
- `ManualTestGuide/MILESTONE1_MANUAL_TESTS.md`

For documents/ingestion testing, make sure both API and worker are running before testing upload and queue flow.

## Auth endpoints provided by the web SDK

- `http://localhost:3000/auth/login`
- `http://localhost:3000/auth/logout`
- `http://localhost:3000/auth/profile`

Quick Auth0 validation:

1. Start web app: `pnpm --filter @meridian/web dev`
2. Open `http://localhost:3000`
3. Click **Login** and authenticate via Auth0
4. Confirm you return to `/` as signed in
5. Visit `/auth/logout` and confirm sign-out

## Useful commands

- `make setup` – full local project setup
- `make dev` – run frontend and backend
- `make dev-api` – run backend only
- `make dev-web` – run frontend only
- `make dev-worker` – run ingestion worker only
- `make lint` – run lint checks
- `make format` – format code
- `make test` – run tests
- `make db-migrate` – apply API migrations
- `make db-revision msg='name'` – create new migration

## Commit-time quality checks (auto-run on `git commit`)

This repo uses a git pre-commit hook to enforce baseline quality automatically.

What runs on each commit:

- Backend lint auto-fix: `ruff check --fix`
- Backend format: `ruff format`
- Backend tests: `pytest -q`
- Frontend typecheck: `pnpm --filter @meridian/web typecheck`

Setup (one-time per clone):

```bash
cd /Users/pranav/Desktop/RAG/Meridian
pnpm install
pnpm run prepare
```

If any check fails, commit is blocked until fixed.

## Production DB runbook

Use Alembic migrations as the **only** schema change mechanism in production.
Do not auto-create tables at API startup.

### 1) Pre-deploy checks

1. Ensure target DB URL is correct and points to the intended environment.
2. Ensure migrations are committed in repo (`apps/api/alembic/versions`).
3. Validate migration status:

```bash
cd apps/api
.venv/bin/alembic heads
.venv/bin/alembic current
```

If `current` is behind `heads`, migration is required before app rollout.

### 2) Standard deploy sequence (recommended)

1. Deploy application artifact/container (without shifting traffic yet).
2. Run migrations once:

```bash
make db-migrate
```

3. Verify migration revision:

```bash
cd apps/api && .venv/bin/alembic current
```

4. Start/roll traffic to new API version.
5. Run health checks (`/health`) and smoke tests.

### 3) Rollback strategy

- Prefer **roll-forward** fixes for failed migrations in production.
- Use `alembic downgrade` only when explicitly tested and data-safe.
- If a migration fails mid-release:
  1. Stop rollout.
  2. Restore traffic to last healthy app version.
  3. Repair migration and deploy a new forward migration.

### 4) Zero-downtime migration rules

For customer-facing releases, follow expand/contract:

1. **Expand**: add nullable columns/tables/indexes first.
2. Deploy app that writes to both old/new shape if needed.
3. Backfill data via controlled job.
4. **Contract**: remove old columns/constraints in a later release.

Avoid destructive changes in the same release where code still depends on old schema.

### 5) Practical commands (operator quick reference)

```bash
# Apply all pending migrations
make db-migrate

# Check current revision
cd apps/api && .venv/bin/alembic current

# Show latest known revision(s)
cd apps/api && .venv/bin/alembic heads

# Create a reviewed migration from model changes
make db-revision msg='describe_change'
```
