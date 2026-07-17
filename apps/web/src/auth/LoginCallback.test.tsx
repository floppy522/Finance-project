import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { LoginCallback } from "./LoginCallback";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

test("exchanges a login token once when StrictMode replays the effect", async () => {
  window.history.replaceState(null, "", "/login?token=single-use-token");
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));

  render(
    <StrictMode>
      <LoginCallback />
    </StrictMode>,
  );

  expect(await screen.findByRole("status")).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith("/api/auth/exchange", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: "single-use-token" }),
  });
});
