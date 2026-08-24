import { defineConfig, devices } from "@playwright/test";

/**
 * Real browser verification for the chat-history and staff-conversations
 * work — the first frontend test infrastructure in this repo. Assumes the
 * Django backend (http://127.0.0.1:8000) is already running separately;
 * only the Next.js dev server is managed here.
 */
export default defineConfig({
  testDir: ".",
  timeout: 45_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 60_000,
    cwd: "..",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
