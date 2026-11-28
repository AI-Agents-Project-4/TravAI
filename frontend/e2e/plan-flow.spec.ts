// The proposal walkthrough (eval case 1): plan a Tokyo trip, compare three
// plans, edit one, redraft around the edits, save, and come back to it.
import { expect, startTrip, test, totalPanel, waitForPlans } from "./fixtures";

const FUJI = "Mount Fuji and Lake Kawaguchi day trip";
const HAKONE = "Hakone hot springs day trip";

test("Tokyo: progress, three different plans, sourced prices", async ({ page }) => {
  await startTrip(page, { destination: "Tokyo, Japan", days: 5, budget: 5000 });
  await expect(page).toHaveURL(/\/trips\//);
  await expect(page.getByText("Found 4 flights, checking hotel prices")).toBeVisible();
  await waitForPlans(page);

  const cards = page.getByRole("article");
  await expect(cards).toHaveCount(3);
  const totals = await cards.locator("p.text-3xl").allInnerTexts();
  expect(new Set(totals).size, `plan totals ${totals.join(", ")}`).toBe(3);
  for (const card of await cards.all()) {
    await expect(card.getByText(/under your \$5,000 budget/)).toBeVisible();
  }

  // Rule 2: every price shows its source and age.
  const sources = page.getByRole("link", { name: /source for/ });
  expect(await sources.count()).toBeGreaterThan(0);
  for (const link of await sources.all()) {
    await expect(link).toHaveAttribute("href", /^https:\/\//);
    await expect(link).toHaveAttribute("target", "_blank");
  }
  await expect(page.getByText(/fetched/).first()).toBeVisible();
});

test("edit, redraft around the edits, save and come back", async ({ page }) => {
  // $3,000 is tight: adding two day trips goes over, so the redraft must drop something.
  await startTrip(page, { destination: "Tokyo, Japan", days: 5, budget: 3000 });
  await waitForPlans(page);
  await page.getByRole("link", { name: "View and edit Temples and history" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Temples and history" })).toBeVisible();

  const total = totalPanel(page).locator("p.text-3xl");
  const before = await total.innerText();

  await page.getByRole("button", { name: "Remove Tea ceremony in Asakusa" }).click();
  await expect(total).not.toHaveText(before);

  await page.getByLabel(`Day to add ${FUJI} to`).selectOption("3");
  await page.getByRole("button", { name: `Add ${FUJI}` }).click();
  await page.getByLabel(`Day to add ${HAKONE} to`).selectOption("4");
  await page.getByRole("button", { name: `Add ${HAKONE}` }).click();
  await page.getByLabel("Move Senso-ji Temple and Asakusa walk to").selectOption("2");
  await expect(totalPanel(page)).toContainText("over your $3,000 budget");

  await page.getByRole("button", { name: "Redraft around my changes" }).click();
  await expect(totalPanel(page)).toContainText("Redrafted.");
  await expect(totalPanel(page)).toContainText("the planner dropped");
  await expect(totalPanel(page)).toContainText("left of your $3,000 budget");

  // Rule 5: the user's edits survive the redraft.
  await expect(page.getByRole("region", { name: "Day 3" })).toContainText(FUJI);
  await expect(page.getByRole("region", { name: "Day 4" })).toContainText(HAKONE);
  await expect(page.getByRole("region", { name: "Day 2" })).toContainText("Senso-ji");
  for (const day of [1, 2, 3, 4, 5]) {
    await expect(page.getByRole("region", { name: `Day ${day}` })).not.toContainText("Tea ceremony");
  }

  await page.getByRole("button", { name: "Save plan" }).click();
  await expect(totalPanel(page)).toContainText("Plan saved.");
  const saved = await total.innerText();

  await page.reload();
  await expect(page.getByRole("button", { name: "Saved" })).toBeVisible();
  await expect(total).toHaveText(saved);
  await expect(page.getByRole("region", { name: "Day 3" })).toContainText(FUJI);
});

test("undo puts the plan back", async ({ page }) => {
  await startTrip(page, { destination: "Tokyo, Japan", days: 5, budget: 5000 });
  await waitForPlans(page);
  await page.getByRole("link", { name: "View and edit Day trips" }).click();
  const total = totalPanel(page).locator("p.text-3xl");
  const before = await total.innerText();
  await page.getByRole("button", { name: /^Remove / }).first().click();
  await expect(total).not.toHaveText(before);
  await page.getByRole("button", { name: "Undo my changes" }).click();
  await expect(total).toHaveText(before);
});
