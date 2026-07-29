import { NextRequest } from "next/server";
import { describe, expect, it, vi } from "vitest";

const { getAccessToken } = vi.hoisted(() => ({ getAccessToken: vi.fn() }));

vi.mock("@/lib/auth0", () => ({ auth0: { getAccessToken } }));

import { proxyMeridianRequest } from "./meridian-bff";

describe("Meridian BFF session handling", () => {
  it("returns a safe 401 envelope when the server session cannot provide a token", async () => {
    process.env.API_BASE_URL = "http://localhost:8000";
    getAccessToken.mockRejectedValueOnce(new Error("session expired"));

    const response = await proxyMeridianRequest(
      new NextRequest("http://localhost:3000/api/meridian/documents"),
      ["documents"],
    );

    expect(response.status).toBe(401);
    await expect(response.json()).resolves.toMatchObject({
      error: {
        code: "AUTHENTICATION_REQUIRED",
        message: "Please sign in to continue",
      },
    });
  });
});
