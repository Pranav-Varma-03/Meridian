import { render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";

import { ChatsIndex } from "./chats-index";

describe("ChatsIndex", () => {
  it("lists owner-scoped conversations with direct links and a new-chat action", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json({
          conversations: [
            {
              id: "11111111-1111-4111-8111-111111111111",
              title: "Quarterly report",
              updated_at: "2026-07-30T00:00:00Z",
              retrieval_scope: { mode: "all", collection_ids: [], version: 1 },
            },
          ],
          total: 1,
        })
      )
    );

    render(
      <SWRConfig value={{ provider: () => new Map(), shouldRetryOnError: false }}>
        <ChatsIndex />
      </SWRConfig>
    );

    expect(await screen.findByRole("link", { name: /Quarterly report/ })).toHaveAttribute(
      "href",
      "/chat/11111111-1111-4111-8111-111111111111"
    );
    expect(screen.getByRole("link", { name: "New chat" })).toHaveAttribute("href", "/new");
  });
});
