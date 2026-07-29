import { describe, expect, it } from "vitest";

import { apiErrorFromResponse, toDocumentViewModel } from "./contracts";

describe("Meridian API contract handling", () => {
  it("uses the documented error envelope and Retry-After header", async () => {
    const response = new Response(
      JSON.stringify({
        error: {
          code: "RATE_LIMITED",
          message: "Too many chat requests",
          request_id: "request-123",
        },
      }),
      { status: 429, headers: { "Retry-After": "12" } },
    );

    const error = await apiErrorFromResponse(response);

    expect(error).toMatchObject({
      code: "RATE_LIMITED",
      message: "Too many chat requests",
      requestId: "request-123",
      retryAfterSeconds: 12,
      status: 429,
    });
  });

  it("never uses arbitrary upstream response text as a user-facing message", async () => {
    const error = await apiErrorFromResponse(new Response("internal stack", { status: 500 }));

    expect(error.message).toBe("Meridian could not complete that request.");
    expect(error.code).toBe("API_REQUEST_FAILED");
  });

  it("maps exact transport fields at the presentation boundary", () => {
    const document = toDocumentViewModel({
      id: "document-1",
      filename: "handbook.pdf",
      status: "ready",
      collection_id: null,
      created_at: "2026-07-29T10:00:00Z",
      chunk_count: 8,
      file_size: 128,
      latest_job: null,
    });

    expect(document.collectionId).toBeNull();
    expect(document.createdAt).toBeInstanceOf(Date);
  });
});
