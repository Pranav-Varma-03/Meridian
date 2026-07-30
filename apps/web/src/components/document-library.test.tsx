import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CollectionManager } from "./collection-manager";
import { DocumentLibrary } from "./document-library";

const document = {
  id: "4a1da5ed-2f29-44bf-948a-5ebbaea69113",
  filename: "handbook.pdf",
  status: "ready" as const,
  collection_id: null,
  created_at: "2026-07-29T10:00:00Z",
  chunk_count: 4,
  file_size: 1024,
  latest_job: {
    id: "d43e2f5c-5dc5-49c4-8cbd-9b2a285ac906",
    status: "ready" as const,
    attempts: 1,
    error: null,
    started_at: null,
    completed_at: null,
    generation: 1,
  },
};

function renderWithFreshCache(children: ReactNode) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}>
      {children}
    </SWRConfig>
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("document-library workspace", () => {
  it("sends the fixed re-ingestion reason through the BFF only when the capability is present", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/documents")) return Response.json({ documents: [document], total: 1 });
      if (path.includes("/collections")) return Response.json({ collections: [], total: 0 });
      if (path.endsWith("/ingest"))
        return Response.json({ job_id: "job", status: "queued" }, { status: 202 });
      throw new Error(`Unexpected request: ${path} ${init?.method}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithFreshCache(<DocumentLibrary canReingest />);
    const reason = await screen.findByLabelText("Re-ingest handbook.pdf");
    fireEvent.change(reason, { target: { value: "manual_repair" } });

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/meridian/ingest",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ document_id: document.id, reason: "manual_repair" }),
        })
      )
    );
  });

  it("creates collections through the BFF and surfaces the mutation result", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST")
        return Response.json(
          {
            id: "collection",
            name: "Product",
            description: null,
            document_count: 0,
            created_at: "2026-07-29T10:00:00Z",
          },
          { status: 201 }
        );
      return Response.json({ collections: [], total: 0 });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithFreshCache(<CollectionManager />);
    fireEvent.change(await screen.findByLabelText("Collection name"), {
      target: { value: "Product" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await screen.findByText("Collection created.");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/meridian/collections",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "Product", description: null }),
      })
    );
  });

  it("renames a collection through the in-product dialog", async () => {
    const collection = {
      id: "collection-1",
      name: "Old name",
      description: null,
      document_count: 0,
      created_at: "2026-07-29T10:00:00Z",
    };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PATCH") return Response.json({ ...collection, name: "New name" });
      return Response.json({ collections: [collection], total: 1 });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithFreshCache(<CollectionManager />);
    fireEvent.click(await screen.findByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("New collection name"), {
      target: { value: "New name" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/meridian/collections/collection-1",
        expect.objectContaining({ method: "PATCH", body: JSON.stringify({ name: "New name" }) })
      )
    );
    expect(await screen.findByText("Collection updated.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Rename collection" })).not.toBeInTheDocument();
  });

  it("waits for delete confirmation and only sends the lifecycle deletion after confirmation", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === "DELETE")
        return Response.json({ message: "Document deleted and cleanup queued" });
      if (path.includes("/documents")) return Response.json({ documents: [document], total: 1 });
      return Response.json({ collections: [], total: 0 });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderWithFreshCache(<DocumentLibrary canReingest={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

    expect(fetchMock).not.toHaveBeenCalledWith(
      `/api/meridian/documents/${document.id}`,
      expect.anything()
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete document" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/meridian/documents/${document.id}`,
        expect.objectContaining({ method: "DELETE" })
      )
    );
    await screen.findByText("Document removed. Cleanup has been queued.");
  });
});
