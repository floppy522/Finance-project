import { useEffect, useState } from "react";

import { exchangeLoginToken } from "../api/client";

export function LoginCallback() {
  const [status, setStatus] = useState<"loading" | "error">("loading");

  useEffect(() => {
    const url = new URL(window.location.href);
    const token = url.searchParams.get("token");

    // Do not leave a one-time credential in the browser history.
    window.history.replaceState(null, "", `${url.pathname}${url.hash}`);

    if (!token) {
      setStatus("error");
      return;
    }

    void exchangeLoginToken(token)
      .then(() => window.location.replace("/"))
      .catch(() => setStatus("error"));
  }, []);

  if (status === "loading") {
    return <p role="status">Выполняем вход…</p>;
  }

  return <p role="alert">Ссылка для входа недействительна или истекла. Запросите новую командой /login.</p>;
}
