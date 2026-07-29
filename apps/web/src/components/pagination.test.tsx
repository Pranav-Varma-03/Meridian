import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Pagination } from "./pagination";

describe("Pagination", () => {
  it("renders horizontal page controls for ten-record pages and changes pages", () => {
    const onPageChange = vi.fn();
    render(<Pagination currentPage={2} onPageChange={onPageChange} pageSize={10} total={35} />);

    expect(screen.getByRole("navigation", { name: "Pagination" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "4" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "4" }));
    expect(onPageChange).toHaveBeenCalledWith(4);
  });
});
