import "server-only";

import type { UserProvisionResponse } from "@meridian/shared";

import { auth0 } from "@/lib/auth0";

function apiBaseUrl(): string | null {
  const configured = process.env.API_BASE_URL;
  if (!configured) {
    return null;
  }

  try {
    return new URL(configured).toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

/** Provisioning is best-effort; a temporary API outage must not prevent login. */
export async function provisionAuthenticatedUser(): Promise<void> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    console.error("Missing or invalid API_BASE_URL for Meridian user provisioning");
    return;
  }

  try {
    const accessToken = await auth0.getAccessToken();
    const response = await fetch(`${baseUrl}/api/v1/users/me`, {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken.token}` },
      cache: "no-store",
    });

    if (!response.ok) {
      console.error("Meridian user provisioning failed", { status: response.status });
      return;
    }

    await response.json().catch(() => null as UserProvisionResponse | null);
  } catch {
    console.error("Meridian user provisioning request failed");
  }
}
