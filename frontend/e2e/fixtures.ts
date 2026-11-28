import { test as base, expect, type Page } from "@playwright/test";

/** Every test fails if the browser logs an error or a page throws. */
export const test = base.extend<{ browserErrors: string[] }>({
  browserErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (m) => {
        if (m.type() === "error") errors.push(`console: ${m.text()}`);
      });
      page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
      await use(errors);
      expect(errors, "browser errors during the test").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

type TripInput = {
  mode?: "fly" | "drive";
  origin?: string;
  destination: string;
  days: number;
  budget: number;
};

/** Fills the home-page form and submits it. */
export async function startTrip(page: Page, { mode = "fly", origin = "DEN", destination, days, budget }: TripInput) {
  await page.goto("/");
  if (mode === "drive") await page.getByRole("radio", { name: "Drive" }).check();
  await page.getByLabel(mode === "fly" ? "Flying from" : "Driving from").fill(origin);
  await page.getByLabel("Destination").fill(destination);
  await page.getByLabel("Days").fill(String(days));
  await page.getByLabel("Total budget").fill(String(budget));
  await page.getByRole("button", { name: "Plan my trip" }).click();
}

/** Waits for the mock research to finish and the three plans to show. */
export async function waitForPlans(page: Page) {
  await expect(page.getByRole("heading", { name: "Three ways to do this trip" })).toBeVisible({ timeout: 20_000 });
}

/** The plan editor's running-total panel. */
export const totalPanel = (page: Page) => page.getByRole("complementary", { name: "Running total" });
