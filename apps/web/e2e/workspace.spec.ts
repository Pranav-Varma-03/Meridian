import { expect, test } from "@playwright/test";

test.describe("Meridian workspace fixture journeys", () => {
  test("renders the signed-out landing route", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: /log in/i })).toBeVisible();
  });
});
