# Meridian

Meridian is a monorepo for a production-ready RAG application.
It has:

- `apps/web` → Next.js frontend
- `apps/api` → FastAPI backend
- `packages/shared` → shared TypeScript types

## Local setup

1. Create environment file:

```bash
cp .env.example .env
```

Fill `.env` with your credentials, especially:

- `DATABASE_URL` → Supabase Postgres connection string (must include `sslmode=require`)
- `REDIS_URL`
- `OPENAI_API_KEY`
- `PINECONE_API_KEY`
- Auth values (`AUTH0_DOMAIN`, `AUTH0_AUDIENCE`, `AUTH0_CLIENT_ID`)
- `APP_BASE_URL`
- `AUTH0_CLIENT_SECRET`
- `AUTH0_SECRET`
- `API_BASE_URL` (for web→api server-side calls, e.g. `http://localhost:8000`)

The web app reads Auth0 values from this same root `.env` file (no `.env.local` needed).
The web scripts also disable Next telemetry in dev/build/start to avoid network timeout noise in restricted networks.

Auth0 quick setup for local development (official `@auth0/nextjs-auth0` flow):

- `AUTH0_DOMAIN=<your-auth0-tenant-domain>`
- `AUTH0_CLIENT_ID=<your-auth0-client-id>`
- Configure in Auth0 dashboard:
  - Allowed Callback URLs: `http://localhost:3000/auth/callback`
  - Allowed Logout URLs: `http://localhost:3000`
  - Application Type: `Regular Web Application`
  - Token Endpoint Authentication Method: `client_secret_post`

Recommended `.env` Auth0 block:

```env
APP_BASE_URL=http://localhost:3000
AUTH0_DOMAIN=<your-auth0-tenant-domain>
AUTH0_CLIENT_ID=<your-auth0-client-id>
AUTH0_CLIENT_SECRET=your-auth0-client-secret
AUTH0_SECRET=<generate with: openssl rand -hex 32>
AUTH0_AUDIENCE=<your-auth0-api-identifier>
```

Important for API connectivity/user provisioning:

- In Auth0, create/configure an **API** with identifier matching `AUTH0_AUDIENCE`.
- Access tokens used by the web app must have:
  - `aud` = your `AUTH0_AUDIENCE`
  - `iss` = `https://<AUTH0_DOMAIN>/`

After login/signup, the web app calls `POST /api/v1/users/me` with the Auth0 access token.
That endpoint verifies JWT and upserts the user into Postgres (`users` table).

2. Install dependencies:

```bash
make setup
```

3. Start the app:

```bash
make dev
```

To run ingestion worker separately (recommended in local dev):

```bash
make dev-worker
```

4. Run API migrations:

```bash
make db-migrate
```

Open:

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`

## Collections API (implemented)

`/api/v1/collections` endpoints are now fully DB-backed and user-scoped:

- `POST /api/v1/collections`
- `GET /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `PATCH /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`

Notes:

- All collection routes require Auth0 bearer token auth.
- Collection names are enforced as unique per user (case-insensitive).
- List/detail responses include `document_count`.
- Delete returns `200` with `{ "message": "Collection deleted" }`.

## Documents + Ingestion APIs (implemented)

`/api/v1/documents` now includes DB-backed, user-scoped metadata endpoints:

- `POST /api/v1/documents/upload`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}`
- `DELETE /api/v1/documents/{document_id}`

`/api/v1/ingest` lifecycle endpoints are also available:

- `POST /api/v1/ingest` (queue ingestion for an existing document)
- `GET /api/v1/ingest/{job_id}` (fetch ingestion job status)

Notes:

- Document upload creates both a `documents` record and an `ingestion_jobs` record in `queued` state.
- Upload validations enforce supported MIME types (PDF/DOCX/TXT) and max size of 10MB.
- `POST /api/v1/ingest` is idempotent for active jobs: if the latest job for a document is already `queued`/`processing`, the API returns that existing job instead of creating a duplicate.
- Uploaded/manual-ingest jobs are pushed to Redis queue (`INGESTION_QUEUE_KEY`) and consumed by background worker.
- All document and ingestion operations are authenticated and scoped to the current user.

Auth endpoints provided by the SDK:

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

- `make dev` – run frontend and backend
- `make dev-api` – run backend only
- `make dev-web` – run frontend only
- `make lint` – run lint checks
- `make format` – format code
- `make test` – run tests
- `make db-migrate` – apply API migrations (Supabase/Postgres)
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

## Production DB Runbook

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