import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { fetchTransactions } from "../api/client";
import { TransactionList } from "./TransactionList";

const expenseCategories = [
  { code: "expense.groceries", transaction_type: "expense", name_ru: "Продукты" },
  { code: "expense.other", transaction_type: "expense", name_ru: "Прочее" },
];

const incomeCategories = [
  { code: "income.salary", transaction_type: "income", name_ru: "Зарплата" },
  { code: "income.other", transaction_type: "income", name_ru: "Прочий доход" },
];

const defaultTransactions = [
  {
    id: "00000000-0000-0000-0000-000000000001",
    owner: 1,
    transaction_type: "expense",
    direction: "normal",
    amount_kopecks: 35000,
    occurred_at: "2026-07-17T12:00:00Z",
    created_at: "2026-07-17T12:00:00Z",
    description: "Кофе",
    source: "telegram",
    source_event_id: null,
    category_code: "expense.other",
    category_source: "fallback",
    category_confidence: 0,
    needs_category_review: true,
  },
  {
    id: "00000000-0000-0000-0000-000000000002",
    owner: 1,
    transaction_type: "income",
    direction: "normal",
    amount_kopecks: 150_000_00,
    occurred_at: "2026-07-17T21:30:00Z",
    created_at: "2026-07-17T21:30:00Z",
    description: "Зарплата",
    source: "telegram",
    source_event_id: "telegram:midnight",
    category_code: "income.salary",
    category_source: "rules",
    category_confidence: 100,
    needs_category_review: false,
  },
];

interface MockFetchOptions {
  transactions?: typeof defaultTransactions;
  timezone?: string;
  patchStatus?: number;
  patchGate?: Promise<void>;
  errorRoute?: "categories" | "transactions" | "user";
}

function renderList() {
  const client = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retryDelay: 0 },
    },
  });

  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <TransactionList />
      </QueryClientProvider>,
    ),
  };
}

function mockDashboard(options: MockFetchOptions = {}) {
  let transactions = structuredClone(options.transactions ?? defaultTransactions);

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");

    if (options.errorRoute === "user" && url.pathname === "/api/auth/me") {
      return new Response(null, { status: 500 });
    }
    if (options.errorRoute === "categories" && url.pathname === "/api/categories") {
      return new Response(null, { status: 500 });
    }
    if (options.errorRoute === "transactions" && url.pathname === "/api/transactions") {
      return new Response(null, { status: 500 });
    }

    if (url.pathname === "/api/auth/me") {
      return jsonResponse({ telegram_user_id: 1, timezone: options.timezone ?? "Europe/Moscow" });
    }

    if (url.pathname === "/api/categories") {
      return jsonResponse(
        url.searchParams.get("transaction_type") === "expense"
          ? expenseCategories
          : incomeCategories,
      );
    }

    if (url.pathname === "/api/transactions" && (init?.method ?? "GET") === "GET") {
      const categoryCode = url.searchParams.get("category_code");
      const review = url.searchParams.get("needs_category_review");
      const filtered = transactions.filter(
        (transaction) =>
          (categoryCode === null || transaction.category_code === categoryCode) &&
          (review === null || transaction.needs_category_review === (review === "true")),
      );
      return jsonResponse(filtered);
    }

    const categoryMatch = url.pathname.match(/^\/api\/transactions\/([^/]+)\/category$/);
    if (categoryMatch && init?.method === "PATCH") {
      await options.patchGate;
      if (options.patchStatus && options.patchStatus !== 200) {
        return new Response(null, { status: options.patchStatus });
      }

      const request = JSON.parse(String(init.body)) as { category_code: string };
      const transaction = transactions.find(({ id }) => id === categoryMatch[1]);
      if (!transaction) return new Response(null, { status: 404 });

      transaction.category_code = request.category_code;
      transaction.category_source = "manual";
      transaction.category_confidence = 100;
      transaction.needs_category_review = false;
      return jsonResponse(transaction);
    }

    throw new Error(`Unexpected fetch: ${String(input)}`);
  });

  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch401() {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("loads both catalogs with credentials and renders type-compatible category controls", async () => {
  const fetchMock = mockDashboard();
  renderList();

  const coffeeCategory = await screen.findByLabelText("Категория: Кофе");
  expect(coffeeCategory).toHaveValue("expense.other");
  expect(within(coffeeCategory).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual([
    "expense.groceries",
    "expense.other",
  ]);

  const salaryCategory = screen.getByLabelText("Категория: Зарплата");
  expect(within(salaryCategory).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual([
    "income.salary",
    "income.other",
  ]);
  expect(screen.getByText("Проверьте")).toBeInTheDocument();
  expect(screen.getByText("Категория требует проверки")).toBeInTheDocument();

  expect(fetchMock).toHaveBeenCalledWith("/api/transactions", { credentials: "include" });
  expect(fetchMock).toHaveBeenCalledWith("/api/auth/me", { credentials: "include" });
  expect(fetchMock).toHaveBeenCalledWith("/api/categories?transaction_type=expense", {
    credentials: "include",
  });
  expect(fetchMock).toHaveBeenCalledWith("/api/categories?transaction_type=income", {
    credentials: "include",
  });
});

test("renders integer kopecks as rubles in the owner timezone", async () => {
  mockDashboard();
  renderList();

  expect(
    await screen.findByText((content) => content.replace(/\u00a0/g, " ") === "350,00 ₽"),
  ).toBeInTheDocument();
  expect(await screen.findByText("18 июл. 2026 г.")).toBeInTheDocument();
});

test("puts only the selected category and review filters in the transaction URL", async () => {
  const fetchMock = mockDashboard();
  renderList();

  fireEvent.change(await screen.findByLabelText("Фильтр по категории"), {
    target: { value: "expense.groceries" },
  });
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/transactions?category_code=expense.groceries",
      { credentials: "include" },
    ),
  );

  fireEvent.change(screen.getByLabelText("Фильтр проверки"), {
    target: { value: "true" },
  });
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/transactions?category_code=expense.groceries&needs_category_review=true",
      { credentials: "include" },
    ),
  );
});

test("serializes an explicitly false review filter without an empty query marker", async () => {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse([])));
  vi.stubGlobal("fetch", fetchMock);

  await fetchTransactions({ needsCategoryReview: false });
  await fetchTransactions({ categoryCode: "" });

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    "/api/transactions?needs_category_review=false",
    { credentials: "include" },
  );
  expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/transactions", {
    credentials: "include",
  });
});

test("waits for PATCH, prevents another edit, then refetches server-derived category data", async () => {
  let releasePatch!: () => void;
  const patchGate = new Promise<void>((resolve) => {
    releasePatch = resolve;
  });
  const fetchMock = mockDashboard({ patchGate });
  renderList();

  const category = await screen.findByLabelText("Категория: Кофе");
  fireEvent.change(category, { target: { value: "expense.groceries" } });

  await waitFor(() => expect(category).toBeDisabled());
  expect(category).toHaveValue("expense.other");
  expect(screen.getByLabelText("Категория: Зарплата")).toBeDisabled();
  expect(
    fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/category")),
  ).toHaveLength(1);

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/transactions/00000000-0000-0000-0000-000000000001/category",
    {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category_code: "expense.groceries" }),
    },
  );

  releasePatch();

  await waitFor(() => expect(category).toHaveValue("expense.groceries"));
  expect(category).toBeEnabled();
  expect(screen.queryByText("Проверьте")).not.toBeInTheDocument();
  await waitFor(() => {
    expect(
      fetchMock.mock.calls.filter(
        ([input]) => String(input) === "/api/categories?transaction_type=expense",
      ),
    ).toHaveLength(2);
  });
});

test("keeps the previous category and shows an error when PATCH fails", async () => {
  mockDashboard({ patchStatus: 500 });
  renderList();

  const category = await screen.findByLabelText("Категория: Кофе");
  fireEvent.change(category, { target: { value: "expense.groceries" } });

  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось изменить категорию");
  expect(category).toHaveValue("expense.other");
  expect(category).toBeEnabled();
  expect(screen.getByText("Проверьте")).toBeInTheDocument();
});

test("shows a distinct empty state after filters return no transactions", async () => {
  mockDashboard();
  renderList();

  fireEvent.change(await screen.findByLabelText("Фильтр по категории"), {
    target: { value: "expense.groceries" },
  });

  expect(await screen.findByText("По выбранным фильтрам операций нет.")).toBeInTheDocument();
  expect(screen.getByLabelText("Фильтр по категории")).toHaveValue("expense.groceries");
});

test("shows the unfiltered empty state while keeping category filters available", async () => {
  mockDashboard({ transactions: [] });
  renderList();

  expect(await screen.findByText("Операций пока нет.")).toBeInTheDocument();
  expect(screen.getByLabelText("Фильтр по категории")).toBeInTheDocument();
});

test("shows login instruction without retries when a dashboard request returns 401", async () => {
  mockFetch401();
  renderList();

  expect(
    await screen.findByText("Запросите новую ссылку командой /login"),
  ).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(4);
});

test("shows a dashboard error when a category catalog cannot be loaded", async () => {
  mockDashboard({ errorRoute: "categories" });
  renderList();

  expect(
    await screen.findByText("Не удалось загрузить операции. Попробуйте ещё раз."),
  ).toBeInTheDocument();
});
