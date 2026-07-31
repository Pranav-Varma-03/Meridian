import React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

  it("opens a modal mobile drawer and restores opener focus after Escape", async () => {
    render(
      <ThemeProvider>
        <WorkspaceShell capabilities={{ canReingest: false, permissions: [] }} email={null}>
          <p>Workspace content</p>
        </WorkspaceShell>
      </ThemeProvider>
    );

    const opener = screen.getByRole("button", { name: "Open workspace navigation" });
    fireEvent.click(opener);
    const drawer = screen.getByRole("dialog", { name: "Chat navigation" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    expect(within(drawer).getByRole("link", { name: "Meridian new chat" })).toHaveFocus();

    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Chat navigation" })).not.toBeInTheDocument();
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    expect(opener).toHaveFocus();

    fireEvent.click(opener);
    const backdrop = document.querySelector<HTMLElement>('div[aria-hidden="true"]');
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop!);
    expect(screen.queryByRole("dialog", { name: "Chat navigation" })).not.toBeInTheDocument();
    await new Promise((resolve) => window.requestAnimationFrame(resolve));
    expect(opener).toHaveFocus();
  });

  it("keeps Tab focus inside the mobile drawer and closes it on navigation", () => {
    render(
      <ThemeProvider>
        <WorkspaceShell capabilities={{ canReingest: false, permissions: [] }} email={null}>
          <p>Workspace content</p>
        </WorkspaceShell>
      </ThemeProvider>
    );

    fireEvent.click(screen.getByRole("button", { name: "Open workspace navigation" }));
    const drawer = screen.getByRole("dialog", { name: "Chat navigation" });
    const account = within(drawer).getByRole("button", { name: /Signed in/ });
    account.focus();
    fireEvent.keyDown(drawer, { key: "Tab" });
    expect(within(drawer).getByRole("link", { name: "Meridian new chat" })).toHaveFocus();

    fireEvent.click(within(drawer).getByRole("link", { name: "Documents" }), { ctrlKey: true });
    expect(screen.queryByRole("dialog", { name: "Chat navigation" })).not.toBeInTheDocument();
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
