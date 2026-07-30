import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./confirm-dialog";

describe("ConfirmDialog", () => {
  it("focuses Cancel and lets Escape dismiss the dialog", () => {
    const onCancel = vi.fn();
    render(
      <ConfirmDialog onCancel={onCancel} onConfirm={vi.fn()} open title="Delete document?">
        This cannot be undone.
      </ConfirmDialog>,
    );

    expect(screen.getByRole("dialog", { name: "Delete document?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
