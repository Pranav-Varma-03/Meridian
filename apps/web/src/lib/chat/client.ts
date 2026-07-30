import type { ChatRequest, ChatStreamEvent } from "@meridian/shared";

import { apiErrorFromResponse } from "@/lib/api/contracts";
import { decodePostSse } from "@/lib/chat/sse";

export async function streamChat(
  request: ChatRequest,
  options: { signal?: AbortSignal; onEvent: (event: ChatStreamEvent) => void },
): Promise<void> {
  const response = await fetch("/api/meridian/chat", { method: "POST", headers: { Accept: "text/event-stream", "Content-Type": "application/json" }, body: JSON.stringify(request), signal: options.signal });
  if (!response.ok) throw await apiErrorFromResponse(response);
  if (!response.body) throw new Error("Chat did not return a response stream.");
  let terminal = false;
  for await (const event of decodePostSse(response.body)) {
    if (terminal) continue;
    options.onEvent(event);
    if (event.type === "done") terminal = true;
  }
  if (!terminal && !options.signal?.aborted) throw new Error("Chat stream ended before completion.");
}
