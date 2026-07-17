import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { expect, test } from "@playwright/test";

const e2eDirectory = fileURLToPath(new URL(".", import.meta.url));
const apiDirectory = path.resolve(e2eDirectory, "../../apps/api");
const databaseUrl =
  process.env.TEST_DATABASE_URL ??
  "postgresql+asyncpg://moneyflow:moneyflow@127.0.0.1:5432/moneyflow_e2e";
const pythonEnvironment = {
  ...process.env,
  AUTHORIZED_TELEGRAM_USER_ID: "1",
  DATABASE_URL: databaseUrl,
  ENVIRONMENT: "test",
};

function runApi(command: string, arguments_: string[], cwd = e2eDirectory): string {
  const result = spawnSync(
    "uv",
    ["run", "--project", apiDirectory, command, ...arguments_],
    {
      cwd,
      encoding: "utf8",
      env: pythonEnvironment,
    },
  );

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`Python helper failed: ${result.stderr.trim()}`);
  }
  return result.stdout.trim();
}

function runPython(arguments_: string[]): string {
  return runApi("python", arguments_);
}

function telegramUpdate(updateId: number, text: string) {
  return {
    update_id: updateId,
    message: {
      message_id: updateId,
      date: 1_768_651_200,
      chat: { id: 1, type: "private" },
      from: { id: 1, is_bot: false, first_name: "Owner" },
      text,
    },
  };
}

test.beforeAll(() => {
  runPython(["support/prepare_database.py"]);
  runApi("alembic", ["upgrade", "head"], apiDirectory);
  runPython(["-m", "moneyflow.bootstrap"]);
});

test("authorized Telegram expense is idempotent, visible, and uses a one-time login", async ({
  browser,
  page,
  request,
}) => {
  const loginToken = runPython(["support/issue_login_token.py"]);
  expect(loginToken).toMatch(/^[A-Za-z0-9_-]+$/);
  expect(Number(runPython(["support/count_transactions.py"]))).toBe(0);

  const update = telegramUpdate(7001, "кофе 350");
  for (let delivery = 0; delivery < 2; delivery += 1) {
    const response = await request.post("http://127.0.0.1:8000/telegram/webhook", {
      data: update,
      headers: { "X-Telegram-Bot-Api-Secret-Token": "e2e-webhook-secret" },
    });
    expect(response.status()).toBe(204);
  }
  expect(Number(runPython(["support/count_transactions.py"]))).toBe(1);

  const loginUrl = `http://127.0.0.1:5173/login?token=${encodeURIComponent(loginToken)}`;
  await page.goto(loginUrl);
  await expect(page).toHaveURL("http://127.0.0.1:5173/");

  const matchingRow = page
    .getByRole("row")
    .filter({ hasText: "кофе" })
    .filter({ hasText: "350,00 ₽" });
  await expect(matchingRow).toHaveCount(1);

  const cleanContext = await browser.newContext();
  try {
    const reusedTokenPage = await cleanContext.newPage();
    await reusedTokenPage.goto(loginUrl);
    await expect(reusedTokenPage.getByRole("alert")).toContainText(
      "Ссылка для входа недействительна",
    );
  } finally {
    await cleanContext.close();
  }
});
