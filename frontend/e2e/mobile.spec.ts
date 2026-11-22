import { expect, startTrip, test, waitForPlans } from "./fixtures";

test.use({ viewport: { width: 390, height: 844 }, colorScheme: "dark" });

const noSideScroll = (page: import("@playwright/test").Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

test("phone, dark mode: no sideways scrolling, total stays in view while editing", async ({ page }) => {
  await page.goto("/");
  expect(await noSideScroll(page)).toBe(true);

  await startTrip(page, { destination: "Tokyo, Japan", days: 5, budget: 3000 });
  await waitForPlans(page);
  expect(await noSideScroll(page)).toBe(true);

  await page.getByRole("link", { name: "View and edit Temples and history" }).click();
  await page.getByRole("region", { name: "Day 3" }).scrollIntoViewIfNeeded();
  expect(await noSideScroll(page)).toBe(true);

  // The pinned bar at the bottom shows the total while the full panel is off screen.
  const bar = page.locator("div.fixed.bottom-0");
  await expect(bar).toBeInViewport();
  await expect(bar).toContainText("left");
  await page.getByRole("button", { name: "Add Mount Fuji and Lake Kawaguchi day trip" }).click();
  await page.getByRole("button", { name: "Add Hakone hot springs day trip" }).click();
  await expect(bar).toContainText("over budget");
});
