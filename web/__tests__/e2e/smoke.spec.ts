import { test, expect } from "@playwright/test";

test.describe("Marketing pages", () => {
  test("landing page renders headline and CTA", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("link", { name: /start free trial/i }).first()).toBeVisible();
  });

  test("pricing page renders all five tiers", async ({ page }) => {
    await page.goto("/pricing");
    for (const tier of ["Trial", "Basic", "Pro", "Ultra", "Enterprise"]) {
      await expect(page.getByRole("heading", { name: tier, level: 2 })).toBeVisible();
    }
  });

  test("legal page renders privacy and terms headings", async ({ page }) => {
    await page.goto("/legal");
    await expect(page.getByRole("heading", { name: /privacy/i })).toBeVisible();
    await expect(page.getByRole("heading", { name: /terms/i })).toBeVisible();
  });
});

test.describe("Login page", () => {
  test("renders Clerk sign-in UI", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByText(/securely sign in/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /continue/i })).toBeVisible();
  });

  test("does not render legacy API-key login controls", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByLabel(/api key/i)).toHaveCount(0);
  });
});

test.describe("App redirect", () => {
  test("redirects unauthenticated dashboard visit to login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });
});
