# Meridian – Required Account Setup (Milestone 1)

I cannot create third-party accounts on your behalf, but this is everything you need to set up and share/configure to run Milestone 1 end-to-end.

## 1) Supabase (Postgres)
- Create a Supabase project.
- Go to **Project Settings → Database**.
- Copy the **connection string (pooler)** and set:
  - `DATABASE_URL=postgresql+asyncpg://...?...sslmode=require`

## 2) Upstash Redis (or equivalent Redis)
- Create a Redis database.
- Copy the TLS URL and set:
  - `REDIS_URL=rediss://...`

## 3) OpenAI
- Create API key.
- Set:
  - `OPENAI_API_KEY=...`

## 4) Pinecone
- Create API key and index.
- Set:
  - `PINECONE_API_KEY=...`
  - `PINECONE_INDEX_NAME=rag-documents` (or your chosen index)

## 5) Auth0
- Create tenant + API/application.
- For this project, use:
  - Tenant/domain: `dev-5id1h7gt1pxdc4mu.us.auth0.com`
  - Client ID: `JVYswU8oUNT6pCaeuVUS0gveUsNHYK36`
- In **Auth0 Dashboard → Applications → Your App → Settings**, configure:
  - **Application Type**: `Regular Web Application`
  - **Token Endpoint Authentication Method**: `client_secret_post`
  - **Allowed Callback URLs**: `http://localhost:3000/auth/callback`
  - **Allowed Logout URLs**: `http://localhost:3000`
  - (Optional) **Allowed Web Origins**: `http://localhost:3000`
- Set:
  - `AUTH0_DOMAIN=...`
  - `AUTH0_AUDIENCE=...`
  - `AUTH0_CLIENT_ID=...`
  - `AUTH0_CLIENT_SECRET=...`
  - `AUTH0_SECRET=...` (generate with `openssl rand -hex 32`)

### Auth0 verification checklist
- Confirm root `.env` contains all required Auth0 vars (no `.env.local`):
  - `APP_BASE_URL=http://localhost:3000`
  - `AUTH0_DOMAIN=dev-5id1h7gt1pxdc4mu.us.auth0.com`
  - `AUTH0_CLIENT_ID=JVYswU8oUNT6pCaeuVUS0gveUsNHYK36`
  - `AUTH0_CLIENT_SECRET=...`
  - `AUTH0_SECRET=...`
- Run web app:
  - `pnpm --filter @meridian/web dev`
- Validate auth flow in browser:
  - Visit `http://localhost:3000`
  - Click Login (`/auth/login`)
  - Complete Auth0 login and verify redirect back to `/`
  - Visit `/auth/profile` and verify session data is returned
  - Visit `/auth/logout` and verify session is cleared

## 6) Local env file
From repo root:

```bash
cp .env.example .env
```

Fill all fields above before running migrations/app startup.
For the web Auth0 SDK in this monorepo, keep these in the same root `.env`:
- `APP_BASE_URL`
- `AUTH0_DOMAIN`
- `AUTH0_CLIENT_ID`
- `AUTH0_CLIENT_SECRET`
- `AUTH0_SECRET`

Note: web scripts load env from root `.env` and set `NEXT_TELEMETRY_DISABLED=1` to avoid noisy network timeout checks in restricted environments.
