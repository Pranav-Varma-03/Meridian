import { describe, expect, it } from "vitest";

import { unauthenticatedWorkspaceRedirect } from "./workspace-session";

describe("workspace session navigation", () => {
  it("returns signed-out workspace visitors to the public home page", () => {
    expect(unauthenticatedWorkspaceRedirect()).toBe("/");
  });
});
