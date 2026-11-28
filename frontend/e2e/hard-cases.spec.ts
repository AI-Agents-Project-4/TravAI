// Eval cases 2, 4 and 5: a drive day trip, an impossible budget, and the
// hard case where a safety warning must come before any plans.
import { expect, startTrip, test, waitForPlans } from "./fixtures";

test("Japan, 30 days, $500: honestly not feasible (rule 3)", async ({ page }) => {
  await startTrip(page, { destination: "Japan", days: 30, budget: 500 });
  await expect(page.getByRole("heading", { name: "This trip doesn't fit the budget" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Minimum estimated cost")).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(0);
  await page.getByRole("link", { name: "Change the trip" }).click();
  await expect(page.getByLabel("Destination")).toHaveValue("Japan");
});

test("Ukraine: warn first, then let the user decide (rule 4)", async ({ page }) => {
  await startTrip(page, { destination: "Kyiv, Ukraine", days: 3, budget: 1000 });
  const warning = page.getByRole("region", { name: "Before you plan this trip" });
  await expect(warning).toContainText("Safety:");
  await expect(page).toHaveURL("/");

  await page.getByRole("button", { name: "Change my trip" }).click();
  await expect(page.getByLabel("Destination")).toHaveValue("Kyiv, Ukraine");

  await page.getByRole("button", { name: "Plan my trip" }).click();
  await page.getByRole("button", { name: "Proceed anyway" }).click();
  await waitForPlans(page);
  await expect(page.getByText("Safety:").filter({ visible: true })).toHaveCount(1);
  await expect(page.getByRole("article")).toHaveCount(3);

  // Back on the home page the form is fresh: usable, inputs kept, no old warning.
  await page.getByRole("link", { name: "TravAI" }).click();
  await expect(page.getByRole("button", { name: "Plan my trip" })).toBeEnabled();
  await expect(page.getByLabel("Destination")).toHaveValue("Kyiv, Ukraine");
  await expect(page.getByRole("heading", { name: "Before you plan this trip" })).toBeHidden();
});

test("Colorado Springs drive day trip: no flight or hotel", async ({ page }) => {
  await startTrip(page, { mode: "drive", origin: "Golden, CO", destination: "Colorado Springs, CO", days: 1, budget: 500 });
  await waitForPlans(page);
  for (const card of await page.getByRole("article").all()) {
    await expect(card).not.toContainText("Flight");
    await expect(card).not.toContainText("Hotel");
    await expect(card).toContainText("Transport");
  }
});
