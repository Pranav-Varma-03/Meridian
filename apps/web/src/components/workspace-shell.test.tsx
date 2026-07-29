import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceShell } from "./workspace-shell";

const { usePathname } = vi.hoisted(() => ({ usePathname: vi.fn() }));

vi.mock("next/navigation", () => ({ usePathname }));

describe("WorkspaceShell", () => {
  beforeEach(() => {
    usePathname.mockReturnValue("/chat");
  });

  it("renders protected workspace navigation and active route", () => {
    render(
      <WorkspaceShell capabilities={{ canReingest: false }} email="person@example.com">
        <p>Workspace content</p>
      </WorkspaceShell>,
    );

    expect(screen.getAllByRole("navigation", { name: "Workspace" })).not.toHaveLength(0);
    expect(screen.getAllByRole("link", { name: "Chat" })[0]).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("person@example.com")).toBeInTheDocument();
    expect(screen.queryByText("Re-ingestion enabled")).not.toBeInTheDocument();
  });
});
