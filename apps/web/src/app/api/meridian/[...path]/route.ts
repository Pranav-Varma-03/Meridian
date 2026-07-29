import { NextRequest } from "next/server";

import { proxyMeridianRequest } from "@/lib/server/meridian-bff";

export const runtime = "nodejs";

interface RouteContext {
  params: { path: string[] };
}

async function handle(request: NextRequest, { params }: RouteContext): Promise<Response> {
  return proxyMeridianRequest(request, params.path);
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
