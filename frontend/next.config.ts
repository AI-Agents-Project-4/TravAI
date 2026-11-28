import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // E2E tests build into a separate folder (see playwright.config.ts) so a
  // mock-mode build never replaces the normal one.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
