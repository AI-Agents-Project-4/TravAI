import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;

/**
 * End-to-end tests run the real app in a browser against the in-browser mock
 * backend (NEXT_PUBLIC_API_MOCK=true), so they never call paid or live APIs.
 * The app is built into .next-e2e so it doesn't replace your normal build.
 *
 *   pnpm exec playwright install chromium   # once
 *   pnpm e2e                                # or: PW_CHANNEL=chrome pnpm e2e (use installed Chrome)
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    channel: process.env.PW_CHANNEL || undefined,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `pnpm build && pnpm start --port ${PORT}`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    env: { NEXT_PUBLIC_API_MOCK: "true", NEXT_DIST_DIR: ".next-e2e" },
  },
});
