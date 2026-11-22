import { expect, test } from "./fixtures";

test("home page shows the trip form", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "TravAI" })).toBeVisible();
  await expect(page.getByRole("form", { name: "Plan a trip" })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Demo data");
});

test("submitting an empty form shows errors and focuses the first one", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Plan my trip" }).click();
  await expect(page.getByText("Enter where you're flying from")).toBeVisible();
  await expect(page.getByText("Enter where you want to go.")).toBeVisible();
  await expect(page.getByText(/Enter your total budget/)).toBeVisible();
  await expect(page.getByLabel("Flying from")).toBeFocused();
  await expect(page).toHaveURL("/");
});

test("choosing Drive asks where you're driving from", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("radio", { name: "Drive" }).check();
  await expect(page.getByLabel("Driving from")).toBeVisible();
});

test("unknown trip and plan links say so", async ({ page }) => {
  await page.goto("/trips/does-not-exist");
  await expect(page.getByRole("alert").filter({ hasText: "Something went wrong" })).toContainText("Trip not found.");
  await page.goto("/plans/does-not-exist");
  await expect(page.getByRole("alert").filter({ hasText: "open this plan" })).toContainText("Plan not found.");
});
