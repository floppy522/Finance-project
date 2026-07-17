import { useEffect, useState } from "react";

import { exchangeLoginToken } from "../api/client";

let loginExchange: Promise<void> | undefined;

export function LoginCallback() {
  const [status, setStatus] = useState<"loading" | "error">("loading");

  useEffect(() => {
    const url = new URL(window.location.href);
    if (!loginExchange) {
      const token = url.searchParams.get("token");

      // Do not leave a one-time credential in the browser history.
      window.history.replaceState(null, "", `${url.pathname}${url.hash}`);

      if (!token) {
        setStatus("error");
        return;
      }

      loginExchange = exchangeLoginToken(token);
    }

    const currentExchange = loginExchange;
    let active = true;

    void currentExchange.then(
      () => {
        if (loginExchange === currentExchange) loginExchange = undefined;
        if (active) window.location.replace("/");
      },
      () => {
        if (loginExchange === currentExchange) loginExchange = undefined;
        if (active) setStatus("error");
      },
    );

    return () => {
      active = false;
    };
  }, []);

  if (status === "loading") {
    return <p role="status">Выполняем вход…</p>;
  }

  return <p role="alert">Ссылка для входа недействительна или истекла. Запросите новую командой /login.</p>;
}
