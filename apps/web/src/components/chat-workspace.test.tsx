import type { ReactNode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatWorkspace } from "./chat-workspace";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
const { streamChat } = vi.hoisted(() => ({ streamChat: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/chat/client", () => ({ streamChat }));

function renderWorkspace(children: ReactNode) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}>
      {children}
    </SWRConfig>
  );
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("ChatWorkspace", () => {
  it("directs an empty library to document upload instead of allowing chat submission", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ conversations: [], collections: [], total: 0 }))
    );
    renderWorkspace(<ChatWorkspace />);
    expect(await screen.findByText("Upload a document to start")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(screen.getByLabelText("Chat message")).toHaveClass("max-h-40", "overflow-y-auto");
  });

  it("renders restored collection scope selections from conversation detail", async () => {
    const conversationId = "11111111-1111-4111-8111-111111111111";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path.includes(`/conversations/${conversationId}`))
          return Response.json({
            id: conversationId,
            title: "Scoped",
            messages: [],
            retrieval_scope: { mode: "collections", collection_ids: ["collection-1"], version: 2 },
            scope_events: [],
          });
        if (path.includes("/conversations"))
          return Response.json({
            conversations: [
              {
                id: conversationId,
                title: "Scoped",
                updated_at: "2026-07-30T00:00:00Z",
                retrieval_scope: {
                  mode: "collections",
                  collection_ids: ["collection-1"],
                  version: 2,
                },
              },
            ],
            total: 1,
          });
        return Response.json({
          collections: [
            {
              id: "collection-1",
              name: "Product",
              description: null,
              document_count: 1,
              created_at: "2026-07-30T00:00:00Z",
            },
          ],
          total: 1,
        });
      })
    );
    renderWorkspace(<ChatWorkspace conversationId={conversationId} />);
    expect(await screen.findByText(/Selected collections/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Product ×" })).toBeInTheDocument();
  });

  it("prepends older cursor history without replacing the newest page", async () => {
    const conversationId = "33333333-3333-4333-8333-333333333333";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path.includes(`/conversations/${conversationId}`)) {
          const older = path.includes("before_sequence=2");
          return Response.json({
            id: conversationId,
            title: "History",
            messages: older
              ? [{ id: "old", role: "user", content: "Older turn", citations: {}, created_at: "2026-01-01T00:00:00Z" }]
              : [{ id: "new", role: "assistant", content: "Newest turn", citations: {}, created_at: "2026-01-02T00:00:00Z" }],
            retrieval_scope: { mode: "all", collection_ids: [], version: 1 },
            scope_events: [],
            has_more_messages: !older,
            next_before_sequence: older ? null : 2,
          });
        }
        return Response.json({
          collections: [{ id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" }],
          total: 1,
        });
      })
    );
    renderWorkspace(<ChatWorkspace conversationId={conversationId} />);
    expect(await screen.findByText("Newest turn")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load older messages" }));
    expect(await screen.findByText("Older turn")).toBeInTheDocument();
    expect(screen.getByText("Newest turn")).toBeInTheDocument();
  });

  it("replaces the new-chat URL after the terminal stream creates a conversation", async () => {
    streamChat.mockImplementation(
      async (_request: unknown, handlers: { onEvent: (event: any) => void }) => {
        handlers.onEvent({
          type: "done",
          conversation_id: "22222222-2222-4222-8222-222222222222",
          retrieval_scope: { mode: "all", collection_ids: [], version: 1 },
        });
      }
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          collections: [
            {
              id: "collection-1",
              name: "Product",
              description: null,
              document_count: 1,
              created_at: "2026-07-30T00:00:00Z",
            },
          ],
          total: 1,
        })
      )
    );
    renderWorkspace(<ChatWorkspace />);
    fireEvent.change(await screen.findByLabelText("Chat message"), {
      target: { value: "What changed?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/chat/22222222-2222-4222-8222-222222222222")
    );
  });
});
