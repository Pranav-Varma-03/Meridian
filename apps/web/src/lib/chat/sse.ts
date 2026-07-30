import type { ChatStreamEvent } from "@meridian/shared";

export class ChatStreamProtocolError extends Error {
  constructor(message: string) { super(message); this.name = "ChatStreamProtocolError"; }
}

function parseEvent(raw: string): ChatStreamEvent | null {
  const data = raw.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
  if (!data) return null;
  let value: unknown;
  try { value = JSON.parse(data); } catch { throw new ChatStreamProtocolError("Received an invalid chat stream event."); }
  if (!value || typeof value !== "object" || !("type" in value)) throw new ChatStreamProtocolError("Received an invalid chat stream event.");
  const event = value as ChatStreamEvent;
  if (! ["text", "sources", "error", "done"].includes(event.type)) throw new ChatStreamProtocolError("Received an unknown chat stream event.");
  return event;
}

/** Decodes complete SSE records only; network chunks may split JSON arbitrarily. */
export async function* decodePostSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<ChatStreamEvent> {
  const reader = stream.getReader(); const decoder = new TextDecoder(); let buffer = "";
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      buffer += decoder.decode(result.value, { stream: true });
      let boundary: number;
      while ((boundary = buffer.search(/\r?\n\r?\n/)) >= 0) {
        const raw = buffer.slice(0, boundary); const separatorLength = buffer[boundary] === "\r" ? (buffer[boundary + 2] === "\r" ? 4 : 2) : 2;
        buffer = buffer.slice(boundary + separatorLength);
        const event = parseEvent(raw); if (event) yield event;
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) { const event = parseEvent(buffer); if (event) yield event; }
  } finally { reader.releaseLock(); }
}
