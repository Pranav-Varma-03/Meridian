import "server-only";

import { auth0 } from "@/lib/auth0";
import { hasReingestionPermission } from "@/lib/api/permissions";

export interface WorkspaceCapabilities {
  canReingest: boolean;
  permissions: string[];
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const payload = token.split(".")[1];
  if (!payload) {
    return null;
  }

  try {
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const json = Buffer.from(normalized, "base64").toString("utf8");
    const value: unknown = JSON.parse(json);
    return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/**
 * This controls only whether to show the re-ingestion affordance. FastAPI verifies the
 * same bearer token and remains the sole authorization authority for the action.
 */
export async function getWorkspaceCapabilities(): Promise<WorkspaceCapabilities> {
  try {
    const accessToken = await auth0.getAccessToken();
    const claims = decodeJwtPayload(accessToken.token);
    const canReingest = hasReingestionPermission(claims);
    return { canReingest, permissions: canReingest ? ["documents:reingest"] : [] };
  } catch {
    return { canReingest: false, permissions: [] };
  }
}
