import { LoginCallback } from "./auth/LoginCallback";
import { TransactionList } from "./transactions/TransactionList";

export function App() {
  return (
    <main className="app-shell">
      <h1>Moneyflow</h1>
      {window.location.pathname === "/login" ? <LoginCallback /> : <TransactionList />}
    </main>
  );
}
