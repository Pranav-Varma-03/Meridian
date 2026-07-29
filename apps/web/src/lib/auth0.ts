import { Auth0Client } from "@auth0/nextjs-auth0/server";

export const auth0 = new Auth0Client({
  // Meridian uses a token-mediating backend. Browser code talks to same-origin
  // Next.js route handlers and never needs a raw API access token.
  enableAccessTokenEndpoint: false,
  authorizationParameters: {
    audience: process.env.AUTH0_AUDIENCE,
    scope: process.env.AUTH0_SCOPE ?? "openid profile email",
  },
});
