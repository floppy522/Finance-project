import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const e2eDirectory = fileURLToPath(new URL(".", import.meta.url));
const apiDirectory = path.resolve(e2eDirectory, "../../apps/api");
const webDirectory = path.resolve(e2eDirectory, "../../apps/web");
const databaseUrl = process.env.TEST_DATABASE_URL;
if (!databaseUrl) {
  throw new Error("E2E requires an explicit TEST_DATABASE_URL ending in _e2e");
}
const e2eServerIdentity = `moneyflow-e2e-${process.pid}`;
process.env.MONEYFLOW_E2E_SERVER_IDENTITY = e2eServerIdentity;
const serverEnvironment = {
  AUTHORIZED_TELEGRAM_USER_ID: "1",
  DATABASE_URL: databaseUrl,
  ENVIRONMENT: "test",
  MONEYFLOW_E2E_SERVER_IDENTITY: e2eServerIdentity,
  PUBLIC_WEB_URL: "http://127.0.0.1:5173",
  SESSION_COOKIE_SECURE: "false",
  TELEGRAM_BOT_TOKEN: "e2e-bot-token",
  TELEGRAM_WEBHOOK_SECRET: "e2e-webhook-secret",
  TEST_DATABASE_URL: databaseUrl,
};

export default defineConfig({
  testDir: e2eDirectory,
  testMatch: "vertical-slice.spec.ts",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:5173",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: `uv run --project "${apiDirectory}" uvicorn support.app:app --host 127.0.0.1 --port 8000`,
      cwd: e2eDirectory,
      env: serverEnvironment,
      reuseExistingServer: false,
      url: "http://127.0.0.1:8000/health",
    },
    {
      command: `pnpm --dir "${webDirectory}" dev --host 127.0.0.1 --port 5173`,
      cwd: e2eDirectory,
      reuseExistingServer: false,
      url: "http://127.0.0.1:5173",
    },
  ],
});
