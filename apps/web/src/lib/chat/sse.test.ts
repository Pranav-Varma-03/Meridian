import { describe, expect, it } from "vitest";
import { decodePostSse } from "./sse";

function byteStream(parts: string[]) { return new ReadableStream<Uint8Array>({ start(controller) { for (const part of parts) controller.enqueue(new TextEncoder().encode(part)); controller.close(); } }); }

describe("decodePostSse", () => {
  it("handles arbitrary fragmented SSE transport chunks", async () => {
    const events = []; for await (const event of decodePostSse(byteStream(["data: {\"type\":\"te", "xt\",\"content\":\"Hi\"}\n\ndata: {\"type\":\"done\",\"conversation_id\":\"x\",\"retrieval_scope\":{\"mode\":\"all\",\"collection_ids\":[],\"version\":1}}\n\n"]))) events.push(event);
    expect(events.map((event) => event.type)).toEqual(["text", "done"]);
  });
  it("rejects malformed events", async () => {
    await expect(async () => { for await (const _ of decodePostSse(byteStream(["data: nope\n\n"]))) { /* consume */ } }).rejects.toThrow("invalid");
  });
});
