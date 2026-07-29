import "server-only";

import { NextRequest, NextResponse } from "next/server";

import { auth0 } from "@/lib/auth0";
import {
  forwardedRequestHeaders,
  hasSameOrigin,
  isAllowedMeridianRequest,
} from "@/lib/api/bff-policy";

const STATE_CHANGING_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);
const FORWARDED_RESPONSE_HEADERS = [
  "cache-control",
  "content-type",
  "retry-after",
  "x-request-id",
];

function apiErrorResponse(status: number, code: string, message: string): NextResponse {
  return NextResponse.json(
    { error: { code, message, request_id: crypto.randomUUID() } },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

function upstreamBaseUrl(): string | null {
  const configured = process.env.API_BASE_URL;
  if (!configured) return null;
  try {
    return new URL(configured).toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers({ "Cache-Control": "no-store" });
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("X-Content-Type-Options", "nosniff");
  return headers;
}

export async function proxyMeridianRequest(
  request: NextRequest,
  path: readonly string[],
): Promise<Response> {
  if (!isAllowedMeridianRequest(path, request.method)) {
    return apiErrorResponse(404, "BFF_ROUTE_NOT_FOUND", "Meridian route not found");
  }

  if (
    STATE_CHANGING_METHODS.has(request.method) &&
    !hasSameOrigin(request.headers.get("origin"), request.nextUrl.origin)
  ) {
    return apiErrorResponse(403, "BFF_ORIGIN_FORBIDDEN", "Request origin is not allowed");
  }

  const baseUrl = upstreamBaseUrl();
  if (!baseUrl) {
    return apiErrorResponse(503, "API_UNAVAILABLE", "Meridian API is temporarily unavailable");
  }

  let token: string;
  try {
    token = (await auth0.getAccessToken()).token;
  } catch {
    return apiErrorResponse(401, "AUTHENTICATION_REQUIRED", "Please sign in to continue");
  }

  try {
    const upstreamUrl = new URL(`/api/v1/${path.join("/")}`, baseUrl);
    upstreamUrl.search = request.nextUrl.search;
    const method = request.method;
    const body = STATE_CHANGING_METHODS.has(method)
      ? await request.arrayBuffer()
      : undefined;
    const upstream = await fetch(upstreamUrl, {
      method,
      headers: forwardedRequestHeaders(request.headers, token),
      body,
      cache: "no-store",
    });

    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders(upstream),
    });
  } catch {
    return apiErrorResponse(503, "API_UNAVAILABLE", "Meridian API is temporarily unavailable");
  }
}
