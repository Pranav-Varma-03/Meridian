import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AsyncButton, ListSkeleton, TranscriptSkeleton } from "./app-feedback";

describe("workspace feedback primitives", () => {
  it("renders accessible skeletons without motion-only content", () => {
    render(<><ListSkeleton label="Loading documents…" /><TranscriptSkeleton /></>);
    expect(screen.getByRole("status", { name: "Loading documents…" })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status", { name: "Loading conversation…" })).toHaveAttribute("aria-busy", "true");
  });

  it("uses a specific pending label and prevents duplicate clicks", () => {
    render(<AsyncButton pending pendingLabel="Saving…">Save</AsyncButton>);
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
  });
});
