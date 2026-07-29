# Meridian Web Workspace Foundation — Browser Verification

This guide verifies the authenticated web shell and same-origin API boundary added by
the `build-web-workspace-foundation` change. It is browser-first; use Swagger for
backend API behavior as documented in `API_Contract_Reference.md`.

## Prerequisites

From `Meridian/`:

```bash
make db-migrate
make dev-api
make dev-web
```

Configure the root `.env` with a valid `APP_BASE_URL`, Auth0 web application values,
`AUTH0_AUDIENCE`, `AUTH0_SCOPE`, and server-only `API_BASE_URL`. Auth0 must allow
`http://localhost:3000/auth/callback` and `http://localhost:3000` as a logout URL.

## Authenticated workspace

1. Open `http://localhost:3000` while signed out.
2. Confirm the public Meridian landing page offers sign-up and log-in actions.
3. Select **Log in** and complete Auth0 Universal Login.
4. Confirm you arrive at `/chat` and see navigation for Chat, Documents, and
   Collections plus a logout action.
5. Open each navigation destination. At this foundation stage, Documents and
   Collections intentionally show preparation empty states; they do not perform
   document mutations yet.
6. Use `/auth/logout`, then directly open `http://localhost:3000/chat`.
7. Confirm protected content is not displayed and the browser returns to the public
   home page, where the visitor can deliberately choose **Log in** or **Sign up**.

## Same-origin BFF checks

1. While authenticated, open browser developer tools → Network.
2. Future workspace requests must target `/api/meridian/*`, not
   `http://localhost:8000/api/v1/*` directly.
3. Confirm no bearer token is present in browser JavaScript, local storage, request
   URLs, or custom browser request headers.
4. In a later document/chat feature, trigger a normal BFF request and confirm response
   `X-Request-ID` is visible. For a throttled endpoint, confirm the UI uses the API's
   safe message and `Retry-After` value.
5. From a different origin, attempt a state-changing BFF request. It must return a safe
   `403 BFF_ORIGIN_FORBIDDEN` envelope and must not call FastAPI.

## Completion checklist

- [ ] Signed-out landing state works.
- [ ] Authenticated workspace navigation works on desktop and narrow viewport.
- [ ] Logout and direct protected-route access behave correctly.
- [ ] Browser-facing API traffic uses only same-origin `/api/meridian/*` paths.
- [ ] No API bearer token is exposed to browser application code.
- [ ] Error and retry messaging remains safe and actionable.
