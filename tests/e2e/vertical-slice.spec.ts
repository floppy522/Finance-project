import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { expect, test } from "@playwright/test";

const e2eDirectory = fileURLToPath(new URL(".", import.meta.url));
const apiDirectory = path.resolve(e2eDirectory, "../../apps/api");
const databaseUrl = process.env.TEST_DATABASE_URL;
if (!databaseUrl) {
  throw new Error("E2E requires an explicit TEST_DATABASE_URL ending in _e2e");
}
const pythonEnvironment = {
  ...process.env,
  AUTHORIZED_TELEGRAM_USER_ID: "1",
  DATABASE_URL: databaseUrl,
  ENVIRONMENT: "test",
  TEST_DATABASE_URL: databaseUrl,
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

test.beforeAll(async ({ request }) => {
  const identityResponse = await request.get("http://127.0.0.1:8000/health");
  expect(identityResponse.status()).toBe(200);
  expect(identityResponse.headers()["x-moneyflow-e2e-server"]).toBe(
    process.env.MONEYFLOW_E2E_SERVER_IDENTITY,
  );
  runPython(["support/prepare_database.py"]);
  runApi("alembic", ["upgrade", "head"], apiDirectory);
  runPython(["-m", "moneyflow.bootstrap"]);
});

test("batch categories are idempotent, correctable, learned, and use a one-time login", async ({
  browser,
  page,
  request,
}) => {
  const loginToken = runPython(["support/issue_login_token.py"]);
  expect(loginToken).toMatch(/^[A-Za-z0-9_-]+$/);
  expect(Number(runPython(["support/count_transactions.py"]))).toBe(0);

  const update = telegramUpdate(
    7001,
    "15 июля\nкофе 350\nтакси 780\n16 июля\nзарплата +150000\nВкусВилл 4250\nнепонятная строка",
  );
  for (let delivery = 0; delivery < 2; delivery += 1) {
    const response = await request.post("http://127.0.0.1:8000/telegram/webhook", {
      data: update,
      headers: { "X-Telegram-Bot-Api-Secret-Token": "e2e-webhook-secret" },
    });
    expect(response.status()).toBe(204);
  }
  expect(Number(runPython(["support/count_transactions.py"]))).toBe(4);

  const loginUrl = `http://127.0.0.1:5173/login?token=${encodeURIComponent(loginToken)}`;
  await page.goto(loginUrl);
  await expect(page).toHaveURL("http://127.0.0.1:5173/");

  const expectedRows = [
    ["кофе", "expense.cafes", "350,00 ₽"],
    ["такси", "expense.transport", "780,00 ₽"],
    ["зарплата", "income.salary", "150 000,00 ₽"],
    ["ВкусВилл", "expense.groceries", "4 250,00 ₽"],
  ] as const;
  for (const [description, categoryCode, amount] of expectedRows) {
    const row = page.getByRole("row").filter({ hasText: description }).filter({ hasText: amount });
    await expect(row).toHaveCount(1);
    await expect(row.getByLabel(`Категория: ${description}`)).toHaveValue(categoryCode);
  }

  await page.getByLabel("Категория: кофе").selectOption("expense.groceries");
  await expect(page.getByLabel("Категория: кофе")).toHaveValue("expense.groceries");
  await expect(page.getByLabel("Категория: кофе")).toBeEnabled();

  await page.getByLabel("Фильтр проверки").selectOption("true");
  await expect(page.getByText("По выбранным фильтрам операций нет.")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Категория: кофе")).toHaveValue("expense.groceries");

  const learnedUpdate = telegramUpdate(7002, "Кофе! 360");
  const learnedResponse = await request.post("http://127.0.0.1:8000/telegram/webhook", {
    data: learnedUpdate,
    headers: { "X-Telegram-Bot-Api-Secret-Token": "e2e-webhook-secret" },
  });
  expect(learnedResponse.status()).toBe(204);
  expect(Number(runPython(["support/count_transactions.py"]))).toBe(5);

  await page.reload();
  const learnedRow = page
    .getByRole("row")
    .filter({ hasText: "Кофе!" })
    .filter({ hasText: "360,00 ₽" });
  await expect(learnedRow).toHaveCount(1);
  await expect(learnedRow.getByLabel("Категория: Кофе!")).toHaveValue("expense.groceries");

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
