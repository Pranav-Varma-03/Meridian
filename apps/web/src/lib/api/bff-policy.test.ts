import { describe, expect, it } from "vitest";

import {
  allowedMethodsForPath,
  forwardedRequestHeaders,
  hasSameOrigin,
  isAllowedMeridianRequest,
} from "./bff-policy";
import { hasReingestionPermission } from "./permissions";

const id = "152dc37c-de00-47d0-a47c-3a2f7804cbb1";

describe("Meridian BFF policy", () => {
  it("allows only documented routes and methods", () => {
    expect(allowedMethodsForPath(["documents", "upload"])).toEqual(["POST"]);
    expect(allowedMethodsForPath(["chat", "conversations", id])).toEqual(["GET", "DELETE"]);
    expect(isAllowedMeridianRequest(["documents"], "POST")).toBe(false);
    expect(isAllowedMeridianRequest(["..", "secrets"], "GET")).toBe(false);
  });

  it("forwards only safe headers and replaces browser authorization", () => {
    const headers = new Headers({
      Accept: "application/json",
      Authorization: "Bearer browser-token",
      Cookie: "session=secret",
      "Content-Type": "application/json",
      "X-Request-ID": "request-123",
    });

    const forwarded = forwardedRequestHeaders(headers, "server-token");

    expect(forwarded.get("authorization")).toBe("Bearer server-token");
    expect(forwarded.get("cookie")).toBeNull();
    expect(forwarded.get("x-request-id")).toBe("request-123");
  });

  it("requires an exact same origin for mutations", () => {
    expect(hasSameOrigin("http://localhost:3000", "http://localhost:3000")).toBe(true);
    expect(hasSameOrigin("https://attacker.example", "http://localhost:3000")).toBe(false);
    expect(hasSameOrigin(null, "http://localhost:3000")).toBe(false);
  });

  it("treats the re-ingestion capability as a narrow advisory claim", () => {
    expect(hasReingestionPermission({ permissions: ["documents:reingest"] })).toBe(true);
    expect(hasReingestionPermission({ permissions: ["documents:read"] })).toBe(false);
    expect(hasReingestionPermission(null)).toBe(false);
  });
});
