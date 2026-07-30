import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatWorkspace } from "./chat-workspace";

function renderWorkspace(children: ReactNode) { return render(<SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}>{children}</SWRConfig>); }
afterEach(() => vi.unstubAllGlobals());

describe("ChatWorkspace", () => {
  it("directs an empty library to document upload instead of allowing chat submission", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ conversations: [], collections: [], total: 0 })));
    renderWorkspace(<ChatWorkspace />);
    expect(await screen.findByText("Upload a document to start")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("renders restored collection scope selections from conversation detail", async () => {
    const conversationId = "11111111-1111-4111-8111-111111111111";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes(`/conversations/${conversationId}`)) return Response.json({ id: conversationId, title: "Scoped", messages: [], retrieval_scope: { mode: "collections", collection_ids: ["collection-1"], version: 2 }, scope_events: [] });
      if (path.includes("/conversations")) return Response.json({ conversations: [{ id: conversationId, title: "Scoped", updated_at: "2026-07-30T00:00:00Z", retrieval_scope: { mode: "collections", collection_ids: ["collection-1"], version: 2 } }], total: 1 });
      return Response.json({ collections: [{ id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" }], total: 1 });
    }));
    renderWorkspace(<ChatWorkspace />);
    await screen.findByRole("button", { name: "Scoped" });
    screen.getByRole("button", { name: "Scoped" }).click();
    expect(await screen.findByText("Selected collections")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Product ×" })).toBeInTheDocument();
  });
});
