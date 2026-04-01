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

The web app reads Auth0 values from this same root `.env` file (no `.env.local` needed).
The web scripts also disable Next telemetry in dev/build/start to avoid network timeout noise in restricted networks.

Auth0 quick setup for local development (official `@auth0/nextjs-auth0` flow):

- `AUTH0_DOMAIN=dev-5id1h7gt1pxdc4mu.us.auth0.com`
- `AUTH0_CLIENT_ID=JVYswU8oUNT6pCaeuVUS0gveUsNHYK36`
- Configure in Auth0 dashboard:
  - Allowed Callback URLs: `http://localhost:3000/auth/callback`
  - Allowed Logout URLs: `http://localhost:3000`
  - Application Type: `Regular Web Application`
  - Token Endpoint Authentication Method: `client_secret_post`

Recommended `.env` Auth0 block:

```env
APP_BASE_URL=http://localhost:3000
AUTH0_DOMAIN=dev-5id1h7gt1pxdc4mu.us.auth0.com
AUTH0_CLIENT_ID=JVYswU8oUNT6pCaeuVUS0gveUsNHYK36
AUTH0_CLIENT_SECRET=your-auth0-client-secret
AUTH0_SECRET=<generate with: openssl rand -hex 32>
AUTH0_AUDIENCE=https://api.meridian.app
```

2. Install dependencies:

```bash
make setup
```

3. Start the app:

```bash
make dev
```

4. Run API migrations:

```bash
make db-migrate
```

Open:

- Frontend: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`

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