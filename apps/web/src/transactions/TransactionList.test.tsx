import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { TransactionList } from "./TransactionList";

function renderList() {
  const client = new QueryClient();

  return render(
    <QueryClientProvider client={client}>
      <TransactionList />
    </QueryClientProvider>,
  );
}

function mockFetch(body: unknown) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));
}

function mockFetch401() {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("renders integer kopecks as rubles", async () => {
  mockFetch([
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
    },
  ]);
  renderList();

  expect(
    await screen.findByText((content) => content.replace(/\u00a0/g, " ") === "350,00 ₽"),
  ).toBeInTheDocument();
  expect(screen.getByText("Кофе")).toBeInTheDocument();
});

test("shows login instruction on 401", async () => {
  mockFetch401();
  renderList();

  expect(
    await screen.findByText("Запросите новую ссылку командой /login"),
  ).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
});
