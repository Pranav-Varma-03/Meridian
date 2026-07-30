import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceShell } from "./workspace-shell";
import { ThemeProvider } from "./theme-provider";

const { usePathname } = vi.hoisted(() => ({ usePathname: vi.fn() }));

vi.mock("next/navigation", () => ({ usePathname }));

describe("WorkspaceShell", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    usePathname.mockReturnValue("/chat");
  });

  it("renders protected workspace navigation and active route", () => {
    render(
      <ThemeProvider>
        <WorkspaceShell
          capabilities={{ canReingest: false, permissions: [] }}
          email="person@example.com"
        >
          <p>Workspace content</p>
        </WorkspaceShell>
      </ThemeProvider>
    );

    expect(screen.getAllByRole("navigation", { name: "Workspace" })).not.toHaveLength(0);
    expect(screen.getAllByRole("link", { name: "Chat" })[0]).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(screen.getAllByText("person@example.com")).not.toHaveLength(0);
    expect(screen.queryByText("Re-ingestion enabled")).not.toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveClass("overflow-y-auto");
    expect(screen.getByRole("main").parentElement).toHaveClass("h-full");
  });

  it("opens and closes the labeled mobile chat drawer", () => {
    render(
      <ThemeProvider>
        <WorkspaceShell capabilities={{ canReingest: false, permissions: [] }} email={null}>
          <p>Workspace content</p>
        </WorkspaceShell>
      </ThemeProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Open workspace navigation" }));
    expect(screen.getAllByRole("button", { name: "Close chat navigation" })).not.toHaveLength(0);

    fireEvent.click(screen.getAllByRole("button", { name: "Close chat navigation" })[0]);
    expect(screen.queryByRole("button", { name: "Close chat navigation" })).not.toBeInTheDocument();
  });

  it("keeps the sidebar on Documents without rendering a top bar", () => {
    usePathname.mockReturnValue("/documents");

    render(
      <ThemeProvider>
        <WorkspaceShell capabilities={{ canReingest: false, permissions: [] }} email={null}>
          <p>Documents content</p>
        </WorkspaceShell>
      </ThemeProvider>
    );

    expect(screen.getByRole("link", { name: "Meridian new chat" })).toHaveAttribute("href", "/new");
    expect(screen.getByRole("complementary", { name: "Chat navigation" })).toBeInTheDocument();
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
  });
});
