import { useQuery } from "@tanstack/react-query";

import { fetchCurrentUser, fetchTransactions, UNAUTHORIZED } from "../api/client";

const rubles = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function TransactionList() {
  const dashboard = useQuery({
    queryKey: ["transactions", "owner-settings"],
    queryFn: async () => {
      const [transactions, owner] = await Promise.all([
        fetchTransactions(),
        fetchCurrentUser(),
      ]);
      return { transactions, owner };
    },
    retry: (failureCount, error) => error.message !== UNAUTHORIZED && failureCount < 3,
  });

  if (dashboard.isPending) {
    return <p role="status">Загрузка операций…</p>;
  }

  if (dashboard.isError) {
    if (dashboard.error.message === UNAUTHORIZED) {
      return <p role="alert">Запросите новую ссылку командой /login</p>;
    }
    return <p role="alert">Не удалось загрузить операции. Попробуйте ещё раз.</p>;
  }

  if (dashboard.data.transactions.length === 0) {
    return <p>Операций пока нет.</p>;
  }

  return (
    <div className="table-scroll">
      <table>
        <caption>Операции</caption>
        <thead>
          <tr>
            <th scope="col">Дата</th>
            <th scope="col">Описание</th>
            <th scope="col">Сумма</th>
          </tr>
        </thead>
        <tbody>
          {dashboard.data.transactions.map((transaction) => (
            <tr key={transaction.id}>
              <td>
                {new Intl.DateTimeFormat("ru-RU", {
                  dateStyle: "medium",
                  timeZone: dashboard.data.owner.timezone,
                }).format(new Date(transaction.occurred_at))}
              </td>
              <td>{transaction.description}</td>
              <td>{rubles.format(transaction.amount_kopecks / 100)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
