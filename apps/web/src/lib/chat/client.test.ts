import { describe, expect, it, vi } from "vitest";
import { streamChat } from "./client";

function stream(text: string) { return new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new TextEncoder().encode(text)); controller.close(); } }); }

describe("streamChat BFF fixture integration", () => {
  it("sends new-chat scope and consumes text, sources, and terminal scope", async () => {
    const body = 'data: {"type":"text","content":"Answer"}\n\ndata: {"type":"sources","content":[{"document_id":"d","generation":1,"chunk_id":"c","filename":"guide.pdf","page_number":1,"section_heading":null,"excerpt":"Evidence","content_sha256":"hash","score":0.8}]}\n\ndata: {"type":"done","conversation_id":"conversation","retrieval_scope":{"mode":"collections","collection_ids":["collection"],"version":2}}\n\n';
    const fetchMock = vi.fn(async () => new Response(stream(body), { headers: { "Content-Type": "text/event-stream" } })); vi.stubGlobal("fetch", fetchMock);
    const events: string[] = [];
    await streamChat({ query: "Question", retrieval_scope: { mode: "collections", collection_ids: ["collection"] } }, { onEvent: (event) => events.push(event.type) });
    expect(fetchMock).toHaveBeenCalledWith("/api/meridian/chat", expect.objectContaining({ method: "POST" }));
    expect(events).toEqual(["text", "sources", "done"]);
  });
});
