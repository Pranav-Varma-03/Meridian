import { describe, expect, it } from "vitest";

import { hasActiveIngestion, uploadValidationMessage } from "./document-library";

describe("document library helpers", () => {
  it("validates supported upload files before sending them", () => {
    expect(uploadValidationMessage(new File(["x"], "notes.pdf", { type: "application/pdf" }))).toBeNull();
    expect(uploadValidationMessage(new File(["x"], "notes.exe"))).toBe("Upload a PDF, DOCX, or TXT file.");
  });

  it("continues polling only while a latest ingestion job is active", () => {
    const base = { id: "document", filename: "notes.txt", collection_id: null, created_at: "2026-01-01T00:00:00Z", chunk_count: 0, file_size: 1 };
    expect(hasActiveIngestion([{ ...base, status: "ready", latest_job: { id: "job", status: "processing", attempts: 1, error: null, started_at: null, completed_at: null, generation: 1 } }])).toBe(true);
    expect(hasActiveIngestion([{ ...base, status: "ready", latest_job: { id: "job", status: "ready", attempts: 1, error: null, started_at: null, completed_at: null, generation: 1 } }])).toBe(false);
  });
});
