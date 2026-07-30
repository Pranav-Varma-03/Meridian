import { fireEvent, render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import { describe, expect, it, vi } from "vitest";

import { ChatSidebar } from "./chat-sidebar";

vi.mock("next/navigation", () => ({ usePathname: () => "/chat" }));

describe("ChatSidebar", () => {
  it("persists compact mode and restores account-trigger focus after Escape", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json({ conversations: [], total: 0 }))
    );
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <ChatSidebar
          capabilities={{ canReingest: true, permissions: ["documents:reingest"] }}
          email="person@example.com"
        />
      </SWRConfig>
    );
    expect(screen.getByRole("complementary", { name: "Chat navigation" })).toHaveClass("h-full");
    expect(screen.getByRole("link", { name: "Meridian new chat" })).toHaveAttribute("href", "/new");
    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute("href", "/chat");
    expect(screen.getByRole("link", { name: "Documents" })).toHaveAttribute("href", "/documents");
    expect(screen.getByRole("link", { name: "Collections" })).toHaveAttribute(
      "href",
      "/collections"
    );
    fireEvent.click(screen.getByRole("button", { name: "Collapse chat sidebar" }));
    expect(window.localStorage.getItem("meridian-chat-sidebar")).toBe("collapsed");
    fireEvent.click(screen.getByRole("button", { name: "@" }));
    expect(await screen.findByText("documents:reingest")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("documents:reingest")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "@" })).toHaveFocus();
  });
});
