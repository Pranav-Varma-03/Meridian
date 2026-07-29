# Meridian

Meridian is a monorepo for a production-oriented RAG application.

For VS Code launch profiles, safe breakpoint placement, and end-to-end ingestion and
chat debugging flows, see [DEBUGGING.md](DEBUGGING.md).

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
- `API_BASE_URL` (for Next.js server → API calls, e.g. `http://localhost:8000`; do not
  expose it as `NEXT_PUBLIC_API_BASE_URL`)

`OPENAI_API_KEY` is required only when `EMBEDDING_PROVIDER=openai` or when using
OpenAI-backed contextual chunking. Grounded `POST /api/v1/chat` uses OpenRouter and
requires `OPENROUTER_API_KEY`.

The web app reads Auth0 values from the same root `.env` file.
No `.env.local` is required for the current setup.

### 2.1) Web API boundary

The browser does not receive an Auth0 API bearer token. Authenticated browser requests
use the same-origin Next.js BFF under `/api/meridian/*`; the BFF obtains the access
token from the encrypted Auth0 server session, forwards only an allowlisted Meridian
route, and proxies safe headers plus POST-SSE chat bytes without buffering. It rejects
arbitrary upstream targets, browser-supplied `Authorization` headers, and cross-origin
state-changing requests.

Use these browser-facing paths in web features, not direct `API_BASE_URL` requests:

- `/api/meridian/documents` and `/api/meridian/documents/upload`
- `/api/meridian/collections`
- `/api/meridian/ingest`
- `/api/meridian/chat` and `/api/meridian/chat/conversations`

The BFF preserves Meridian's JSON error envelope, `X-Request-ID`, and `Retry-After`.
It is deliberately an allowlist rather than a generic proxy. Auth0's browser access
token endpoint is disabled because Meridian uses this token-mediating backend pattern.

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

### 3.1) Grounded chat configuration

Chat uses the authenticated user's Pinecone namespace only, then validates every
candidate against the active Postgres document generation before it reaches the model.
Pinecone stores retrieval identifiers and small filter metadata only; after a match is
validated, Meridian loads the authoritative chunk text from Postgres by `chunk_id`.
This keeps chat working for older vectors without embedded text metadata and prevents
vector-store metadata from becoming prompt content.
Configure OpenRouter generation and bounded retrieval/history behavior. The default
`openrouter/free` model routes each request to a compatible free model:

```env
OPENROUTER_API_KEY=<your-openrouter-api-key>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
CHAT_MODEL=openrouter/free
CHAT_TEMPERATURE=0.2
CHAT_MAX_OUTPUT_TOKENS=800
CHAT_CONTEXT_BUDGET_TOKENS=6000
CHAT_CONTEXT_WINDOW_TOKENS=16000
CHAT_SAFETY_RESERVE_TOKENS=512
CHAT_SUMMARY_MAX_TOKENS=1000
CHAT_HISTORY_MAX_TOKENS=1800
CHAT_SOURCE_MIN_TOKENS=1200
CHAT_SOURCE_MAX_TOKENS=4000
CHAT_RETRIEVAL_TOP_K=12
CHAT_RETRIEVAL_OVERFETCH=3
CHAT_RETRIEVAL_MAX_SOURCES=6
CHAT_RETRIEVAL_SCORE_THRESHOLD=0.2
CHAT_HISTORY_MAX_MESSAGES=8
CHAT_SOURCE_PER_DOCUMENT_LIMIT=2
```

`POST /api/v1/chat` is a POST-SSE endpoint. Its successful stream emits zero or more
`text` events, exactly one `sources` event, and one `done` event containing the
conversation ID and effective retrieval scope/version. Callers can send
`retrieval_scope` as `{ "mode": "all" }` or
`{ "mode": "collections", "collection_ids": ["<uuid>"] }`; legacy
`collection_ids` remains compatible. New and pre-existing conversations without a
stored scope use all lifecycle-valid user documents, including unfiled documents. If no active qualifying source exists, it returns a grounded
insufficiency answer with an empty `sources` array. Conversations are owner-scoped;
only completed assistant answers are persisted. The generation prompt reserves output
and safety capacity first, then reserves at least `CHAT_SOURCE_MIN_TOKENS` for
lifecycle-validated PDF evidence before adding a rolling conversation summary or a
contiguous suffix of recent turns. It never sends a provider request when no source
can fit. Retrieval uses `CHAT_RETRIEVAL_TOP_K * CHAT_RETRIEVAL_OVERFETCH` candidates,
then applies active-generation, score, and per-document limits before prompt assembly.

The original user message is retained verbatim. A transient standalone rewrite may be
used only for vector search; it is never stored as a user message. Assistant citations
are immutable snapshots of the exact included source generation, locator, bounded
excerpt, and content hash. A historic citation is marked unavailable if its original
document generation is no longer active; it is never silently redirected to a later
re-ingestion generation. Hard document erasure intentionally does not rewrite prior
assistant text or citation snapshots; product-level transcript erasure remains a
separate retention/privacy workflow.

### 3.2) Chat context migration and rollout

Apply Alembic revision `0005_conversation_memory` before deploying this feature. It
backfills a deterministic `sequence_number` from each message's existing
`created_at, id` order without changing message content, then creates the optional
per-conversation memory row lazily after a successful grounded response. The downgrade
removes only the ordering and memory schema; use it only before application code that
requires these fields is deployed. It does not alter existing transcript content.

### 3.2.1) Conversation retrieval scope migration

Apply Alembic revision `0006_conversation_retrieval_scopes` before deploying durable
collection-scoped chat. It is additive: a conversation without a scope row behaves as
synthetic `all`, version `0`. A submitted scope change is stored with the first affected
user-message sequence for timeline display, while the latest scope is restored from one
current-scope row.

### 3.3) Contextual chunking options

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

After login/signup, the server-side web workspace calls `POST /api/v1/users/me` with
the Auth0 access token. That endpoint verifies the JWT and upserts the user in Postgres.

### Development token-claims diagnostic

`GET /api/v1/auth/token-claims` is available only when `ENVIRONMENT=development`.
It verifies the submitted access token normally and returns only `iss`, `aud`, and
`permissions`; it never returns the raw token or profile claims. The route returns
`404` outside development. Use it through Swagger as described in
`ManualTestGuide/API_Contract_Reference.md`.

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
- Document deletion is logical first: the document immediately disappears from
  normal user APIs and a durable purge job deletes recorded vectors (plus legacy
  document-filter matches) from the owner namespace and removes the raw file.
  Pinecone cleanup may therefore complete asynchronously; retryable failures stay
  visible to the purge worker rather than restoring the document to user reads.

### Generation and purge lifecycle

- Alembic `0003_document_ingestion_generations` establishes the document/generation,
  vector-manifest, purge-job, and outbox lifecycle; `0004_add_ingestion_job_retry_schedule`
  adds durable retry scheduling and processing leases. Postgres is the lifecycle
  authority, Redis only wakes workers, and Pinecone is an eventually consistent
  projection in owner namespaces (`user:<user_id>`).
- A repeated identical upload is deduplication, not re-ingestion: it reuses the
  existing user-owned document/job and does not mutate vectors.
- `POST /api/v1/ingest` is the explicit, permission-gated re-ingestion path. It
  creates a pending generation and leaves the active generation searchable until
  the new vectors are fully upserted and activated.
- A completed activation supersedes the prior generation and creates a durable
  generation purge job. Failed pending generations also queue cleanup for any
  partial vector manifest.
- A repeated upload after a failed generation creates a fresh pending generation
  on the same document identity. The failed generation and its purge job are
  retained until cleanup completes, so a partial provider write never loses its
  durable cleanup owner.
- Ingestion checks document lifecycle state when claiming work, before vector
  writes, and during activation. A concurrent deletion fences activation and
  queues compensating cleanup for any vectors already written.
- Ingestion retries use a Postgres-backed full-jitter exponential schedule.
  Workers recover abandoned ingestion jobs after
  `INGESTION_WORKER_STUCK_TIMEOUT_SECONDS`; purge retries use a durable
  `next_attempt_at`, and purge workers recover abandoned running jobs after
  `PURGE_WORKER_STUCK_TIMEOUT_SECONDS`.

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

- `ManualTestGuide/API_Contract_Reference.md`
- `ManualTestGuide/Production_Hardening_Swagger_Manual_Guide.md`

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
- Frontend tests: `pnpm --filter @meridian/web test`

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

## Production operations

`/health/live` confirms that the API process is running and never probes external
dependencies. `/health/ready` checks Postgres, Redis, Pinecone index access, and
generation-provider configuration; it returns `503` when any required dependency is
unavailable. The existing `/health` remains a backwards-compatible Redis/Postgres
status endpoint.

Authenticated cost-bearing routes are Redis-coordinated and fail closed when Redis is
unavailable: chat is limited to 20 requests/minute and uploads to 10 requests/hour by
default. Configure `RATE_LIMIT_*` values per environment; clients receive `429` with
`Retry-After` when over limit and `503` when protection cannot coordinate.

Deploy a lifecycle release in this order: apply its reviewed Alembic migration, deploy
the API, start compatible workers, verify `/health/ready`, then execute the Swagger
smoke test in `ManualTestGuide/Production_Hardening_Swagger_Manual_Guide.md`. Prefer a
forward migration and application rollback; do not reset or drop production tables.

Operations should alert on readiness failures, rate-limit spikes, ingestion/purge jobs
past their lease timeout, retry exhaustion, terminal purge failures, and failed
Pinecone convergence. Logs are structured and deliberately omit credentials, tokens,
prompts, source text, and vectors. Restore from the managed Postgres provider's tested
point-in-time backup process; after restoration, run Alembic `current`, readiness, and
the two-document smoke test before accepting traffic.
