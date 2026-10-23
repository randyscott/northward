import { defineConfig } from "@playwright/test";

// The browser tests start their own `northward serve` on a throwaway database (see e2e/server.ts), so they need a
// built frontend (`npm run build`) and the Python environment (`make install`).
export default defineConfig({
  testDir: "e2e",
  timeout: 240_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { headless: true, viewport: { width: 1440, height: 1000 }, trace: "retain-on-failure" },
});
