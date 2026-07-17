import { defineConfig, devices } from "@playwright/test";
import { fileURLToPath } from "node:url";
import path from "node:path";

const e2eDirectory = fileURLToPath(new URL(".", import.meta.url));
const apiDirectory = path.resolve(e2eDirectory, "../../apps/api");
const webDirectory = path.resolve(e2eDirectory, "../../apps/web");
const databaseUrl =
  process.env.TEST_DATABASE_URL ??
  "postgresql+asyncpg://moneyflow:moneyflow@127.0.0.1:5432/moneyflow_e2e";
const serverEnvironment = {
  AUTHORIZED_TELEGRAM_USER_ID: "1",
  DATABASE_URL: databaseUrl,
  ENVIRONMENT: "test",
  PUBLIC_WEB_URL: "http://127.0.0.1:5173",
  SESSION_COOKIE_SECURE: "false",
  TELEGRAM_BOT_TOKEN: "e2e-bot-token",
  TELEGRAM_WEBHOOK_SECRET: "e2e-webhook-secret",
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
      reuseExistingServer: !process.env.CI,
      url: "http://127.0.0.1:8000/health",
    },
    {
      command: `pnpm --dir "${webDirectory}" dev --host 127.0.0.1 --port 5173`,
      cwd: e2eDirectory,
      reuseExistingServer: !process.env.CI,
      url: "http://127.0.0.1:5173",
    },
  ],
});
