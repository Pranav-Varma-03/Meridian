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
  streamChat.mockReset();
});

function deferred<T>() {
  let resolve: (value: T) => void;
  let reject: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve: resolve!, reject: reject! };
}

describe("ChatWorkspace", () => {
  it("directs an empty library to document upload instead of allowing chat submission", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ conversations: [], collections: [], total: 0 }))
    );
    renderWorkspace(<ChatWorkspace />);
    expect(await screen.findByText("Upload a document to start")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    expect(screen.getByLabelText("Chat message")).toHaveClass("max-h-28", "overflow-y-auto");
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
    expect(await screen.findByRole("button", { name: "Manage retrieval scope: 1 selected collection" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Scoped" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Manage retrieval scope: 1 selected collection" }));
    expect(await screen.findByRole("dialog", { name: "Retrieval scope" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Product ×" })).toBeInTheDocument();
  });

  it("renders assistant content as safe GitHub-flavored Markdown while preserving user text", async () => {
    const conversationId = "11111111-1111-4111-8111-111111111113";
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes(`/conversations/${conversationId}`)) {
          return Response.json({
            id: conversationId,
            title: "Markdown answer",
            messages: [
              { id: "question", role: "user", content: "What changed?", citations: {}, created_at: "2026-07-30T00:00:00Z" },
              {
                id: "answer",
                role: "assistant",
                content: "## Findings\n\n- **Grounded** answer\n- `citation` support\n\n<script>unsafe()</script>",
                citations: {
                  sources: [
                    {
                      document_id: "document-1",
                      generation: 1,
                      chunk_id: "chunk-1",
                      filename: "policy.pdf",
                      page_number: 2,
                      section_heading: null,
                      excerpt: "The grounded policy excerpt.",
                      content_sha256: "hash",
                      score: 0.98,
                    },
                  ],
                },
                created_at: "2026-07-30T00:00:01Z",
              },
            ],
            retrieval_scope: { mode: "all", collection_ids: [], version: 1 },
            scope_events: [],
            has_more_messages: false,
            next_before_sequence: null,
          });
        }
        return Response.json({
          collections: [{ id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" }],
          total: 1,
        });
      })
    );
    renderWorkspace(<ChatWorkspace conversationId={conversationId} />);

    expect(await screen.findByRole("heading", { name: "Findings" })).toBeInTheDocument();
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByText("Grounded").tagName).toBe("STRONG");
    expect(screen.getByText("citation").tagName).toBe("CODE");
    expect(screen.queryByText("unsafe()")).not.toBeInTheDocument();
    expect(screen.getByText("What changed?").tagName).toBe("P");
    fireEvent.click(screen.getByRole("button", { name: "Copy response" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining("## Findings")));
    expect(screen.getByText("Copied")).toBeInTheDocument();
    const sources = screen.getByLabelText("Sources");
    fireEvent.click(sources);
    const pane = await screen.findByRole("complementary", { name: "Sources (1)" });
    expect(pane).toHaveClass("h-full", "shrink-0");
    const source = screen.getByRole("button", { name: /policy\.pdf/i });
    expect(source).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("The grounded policy excerpt.")).not.toBeInTheDocument();
    fireEvent.click(source);
    expect(source).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("The grounded policy excerpt.")).toBeInTheDocument();
    fireEvent.keyDown(pane, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Sources (1)" })).not.toBeInTheDocument());
    expect(sources).toHaveFocus();
  });

  it("switches the inspector between response snapshots and identifies unavailable historic evidence", async () => {
    const conversationId = "11111111-1111-4111-8111-111111111114";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes(`/conversations/${conversationId}`)) {
          return Response.json({
            id: conversationId,
            title: "Evidence",
            messages: [
              {
                id: "first-answer",
                role: "assistant",
                content: "First answer",
                citations: { sources: [{ document_id: "document-one", generation: 1, chunk_id: "chunk-one", filename: "first.pdf", page_number: 1, section_heading: "Overview", excerpt: "First stored excerpt.", content_sha256: "one", score: 0.9 }] },
                created_at: "2026-07-30T00:00:01Z",
              },
              {
                id: "second-answer",
                role: "assistant",
                content: "Second answer",
                citations: { sources: [{ document_id: "document-two", generation: 2, chunk_id: "chunk-two", filename: "second.pdf", page_number: null, section_heading: null, excerpt: "Second historical excerpt.", content_sha256: "two", score: 0.8, available: false, unavailable_reason: "source_unavailable" }] },
                created_at: "2026-07-30T00:00:02Z",
              },
            ],
            retrieval_scope: { mode: "all", collection_ids: [], version: 1 },
            scope_events: [],
            has_more_messages: false,
            next_before_sequence: null,
          });
        }
        return Response.json({ collections: [{ id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" }], total: 1 });
      })
    );

    renderWorkspace(<ChatWorkspace conversationId={conversationId} />);
    const [first, second] = await screen.findAllByLabelText("Sources");
    fireEvent.click(first);
    expect(await screen.findByText("first.pdf")).toBeInTheDocument();
    fireEvent.click(second);
    expect(await screen.findByText("second.pdf")).toBeInTheDocument();
    expect(screen.queryByText("first.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("No longer active")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /second\.pdf/i }));
    expect(screen.getByText("Second historical excerpt.")).toBeInTheDocument();
    expect(screen.getByText(/no longer in your active library/i)).toBeInTheDocument();
    fireEvent.click(second);
    await waitFor(() => expect(screen.queryByRole("complementary")).not.toBeInTheDocument());
    expect(second).toHaveFocus();
  });

  it("uses a focus-contained modal drawer for sources on narrow viewports", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
    const conversationId = "11111111-1111-4111-8111-111111111115";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes(`/conversations/${conversationId}`)) {
          return Response.json({
            id: conversationId,
            title: "Mobile evidence",
            messages: [{ id: "answer", role: "assistant", content: "Answer", citations: { sources: [{ document_id: "document", generation: 1, chunk_id: "chunk", filename: "mobile.pdf", page_number: 3, section_heading: null, excerpt: "Mobile excerpt.", content_sha256: "hash", score: 0.9 }] }, created_at: "2026-07-30T00:00:01Z" }],
            retrieval_scope: { mode: "all", collection_ids: [], version: 1 },
            scope_events: [],
            has_more_messages: false,
            next_before_sequence: null,
          });
        }
        return Response.json({ collections: [{ id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" }], total: 1 });
      })
    );

    renderWorkspace(<ChatWorkspace conversationId={conversationId} />);
    const sources = await screen.findByLabelText("Sources");
    fireEvent.click(sources);
    const drawer = await screen.findByRole("dialog", { name: "Sources (1)" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    const close = drawer.querySelector<HTMLButtonElement>('button[aria-label="Close sources"]');
    expect(close).not.toBeNull();
    expect(close).toHaveFocus();
    fireEvent.keyDown(close!, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: /mobile\.pdf/i })).toHaveFocus();
    fireEvent.keyDown(drawer, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Sources (1)" })).not.toBeInTheDocument());
    expect(sources).toHaveFocus();
  });

  it("preserves the composer and shows a transcript-shaped fallback while conversation detail loads", async () => {
    const conversationId = "11111111-1111-4111-8111-111111111112";
    const detail = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (String(input).includes(`/conversations/${conversationId}`)) return detail.promise;
        return Promise.resolve(Response.json({ collections: [], total: 0 }));
      })
    );

    renderWorkspace(<ChatWorkspace conversationId={conversationId} />);
    expect(await screen.findByRole("status", { name: "Loading conversation…" })).toBeInTheDocument();
    expect(screen.getByLabelText("Chat message")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it("makes collection scope loading visible and prevents scope edits until choices resolve", async () => {
    const collections = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(() => collections.promise));

    renderWorkspace(<ChatWorkspace />);
    expect(await screen.findByRole("button", { name: "Retrieval scope: loading collection choices" })).toBeDisabled();
  });

  it("lets the user add, remove, and clear collections from the compact scope overlay", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          collections: [
            { id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" },
            { id: "collection-2", name: "Research", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" },
          ],
          total: 2,
        })
      )
    );
    renderWorkspace(<ChatWorkspace />);

    const trigger = await screen.findByRole("button", { name: "Manage retrieval scope: All documents" });
    fireEvent.click(trigger);
    expect(await screen.findByText("All ready documents are included.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Add collection to chat scope"), { target: { value: "collection-1" } });
    expect(screen.getByRole("button", { name: "Product ×" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Add collection to chat scope"), { target: { value: "collection-2" } });
    expect(screen.getByRole("button", { name: "Research ×" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Product ×" }));
    expect(screen.queryByRole("button", { name: "Product ×" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear to all documents" }));
    expect(await screen.findByText("All ready documents are included.")).toBeInTheDocument();
  });

  it("closes the scope overlay with Escape and restores focus to its trigger", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          collections: [{ id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" }],
          total: 1,
        })
      )
    );
    renderWorkspace(<ChatWorkspace />);

    const trigger = await screen.findByRole("button", { name: "Manage retrieval scope: All documents" });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Retrieval scope" });
    expect(dialog).toHaveClass("fixed", "sm:absolute", "sm:right-0", "overflow-y-auto");
    expect(dialog).toHaveFocus();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Retrieval scope" })).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it("prepends older cursor history without replacing the newest page", async () => {
    const conversationId = "33333333-3333-4333-8333-333333333333";
    const olderPage = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path.includes(`/conversations/${conversationId}`)) {
          const older = path.includes("before_sequence=2");
          if (older) return olderPage.promise;
          return Response.json({
            id: conversationId,
            title: "History",
            messages: [{ id: "new", role: "assistant", content: "Newest turn", citations: {}, created_at: "2026-01-02T00:00:00Z" }],
            retrieval_scope: { mode: "all", collection_ids: [], version: 1 },
            scope_events: [],
            has_more_messages: true,
            next_before_sequence: 2,
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
    const transcript = screen.getByTestId("conversation-transcript");
    let scrollHeight = 200;
    Object.defineProperties(transcript, {
      scrollHeight: { configurable: true, get: () => scrollHeight },
      clientHeight: { configurable: true, value: 100 },
      scrollTop: { configurable: true, writable: true, value: 0 },
    });
    fireEvent.scroll(transcript);
    const jumpToLatest = await screen.findByRole("button", { name: "Jump to latest" });
    expect(jumpToLatest).toHaveClass("absolute", "bottom-4", "right-4", "h-11", "w-11", "rounded-full", "bg-card", "shadow-lg");
    expect(jumpToLatest).not.toHaveTextContent("Jump to latest");
    fireEvent.click(jumpToLatest);
    expect(transcript.scrollTop).toBe(200);
    transcript.scrollTop = 50;
    fireEvent.scroll(transcript);
    fireEvent.click(screen.getByRole("button", { name: "Load older messages" }));
    scrollHeight = 300;
    olderPage.resolve(
      Response.json({
        id: conversationId,
        title: "History",
        messages: [{ id: "old", role: "user", content: "Older turn", citations: {}, created_at: "2026-01-01T00:00:00Z" }],
        retrieval_scope: { mode: "all", collection_ids: [], version: 1 },
        scope_events: [],
        has_more_messages: false,
        next_before_sequence: null,
      })
    );
    expect(await screen.findByText("Older turn")).toBeInTheDocument();
    expect(screen.getByText("Newest turn")).toBeInTheDocument();
    expect(transcript.scrollTop).toBe(150);
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
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/chat/22222222-2222-4222-8222-222222222222")
    );
  });

  it("keeps a provisional assistant response stable until streamed text arrives and then completes", async () => {
    const stream = deferred<void>();
    let handlers: { onEvent: (event: any) => void } | null = null;
    streamChat.mockImplementation(async (_request: unknown, nextHandlers: { onEvent: (event: any) => void }) => {
      handlers = nextHandlers;
      await stream.promise;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ collections: [{ id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" }], total: 1 }))
    );

    renderWorkspace(<ChatWorkspace />);
    fireEvent.change(await screen.findByLabelText("Chat message"), { target: { value: "What changed?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Searching your documents…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage retrieval scope: All documents" })).toBeDisabled();
    handlers!.onEvent({ type: "sources", content: [] });
    expect(screen.getByText("Searching your documents…")).toBeInTheDocument();
    handlers!.onEvent({ type: "text", content: "A grounded answer." });
    expect(await screen.findByText("A grounded answer.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    handlers!.onEvent({ type: "done", conversation_id: "22222222-2222-4222-8222-222222222222", retrieval_scope: { mode: "all", collection_ids: [], version: 1 } });
    stream.resolve();

    await waitFor(() => expect(screen.getByLabelText("Chat message")).toBeEnabled());
    expect(screen.getByText("Meridian response complete.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Sources"));
    expect(await screen.findByText("No supporting sources were returned for this response.")).toBeInTheDocument();
  });

  it("marks a stopped response as retryable and restores its submitted query", async () => {
    const stream = deferred<void>();
    streamChat.mockImplementation(async () => stream.promise);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ collections: [{ id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" }], total: 1 }))
    );

    renderWorkspace(<ChatWorkspace />);
    fireEvent.change(await screen.findByLabelText("Chat message"), { target: { value: "Retry this question" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByText("Searching your documents…");
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByText(/Meridian · stopped/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry last question" }));
    expect(screen.getByLabelText("Chat message")).toHaveValue("Retry this question");
    stream.reject(new DOMException("Aborted", "AbortError"));
  });

  it("keeps a failed response retryable when the stream reports an error", async () => {
    const stream = deferred<void>();
    let handlers: { onEvent: (event: any) => void } | null = null;
    streamChat.mockImplementation(async (_request: unknown, nextHandlers: { onEvent: (event: any) => void }) => {
      handlers = nextHandlers;
      await stream.promise;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ collections: [{ id: "collection-1", name: "Product", description: null, document_count: 1, created_at: "2026-07-30T00:00:00Z" }], total: 1 }))
    );

    renderWorkspace(<ChatWorkspace />);
    fireEvent.change(await screen.findByLabelText("Chat message"), { target: { value: "Retry failed question" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByText("Searching your documents…");
    handlers!.onEvent({ type: "error", message: "Stream failed" });
    stream.resolve();

    expect(await screen.findByRole("button", { name: "Retry last question" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry last question" }));
    expect(screen.getByLabelText("Chat message")).toHaveValue("Retry failed question");
  });
});
