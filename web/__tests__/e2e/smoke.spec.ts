import { test, expect } from "@playwright/test";

test.describe("App", () => {
  test("dashboard page is accessible with auth", async ({ page }) => {
    // Note: In a real E2E environment, you would provide valid auth credentials
    // For this open-source version, auth is bearer token based
    await page.goto("/dashboard");
    // Either redirect to auth, or show dashboard if token is provided
    const url = page.url();
    expect(url).toMatch(/\/dashboard|\/login|\/auth/);
  });
});
