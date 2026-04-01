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
