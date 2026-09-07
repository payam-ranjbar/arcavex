import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end against the real built application in a browser.
 *
 * Outside Tauri the entry point binds the deterministic fake gateway, so these tests exercise
 * the actual bundle, routing, and styling without a sidecar. Behaviour that needs a real engine
 * is covered by the packaged smoke tests instead.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // Preview the production bundle: what ships is what is tested. The `e2e` script builds it
    // first, so this command only serves and its readiness is a clean signal.
    command: "npx vite preview --port 5174 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
