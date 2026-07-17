import { useQuery } from "@tanstack/react-query";

import { fetchTransactions, UNAUTHORIZED } from "../api/client";

const rubles = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const date = new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" });

export function TransactionList() {
  const transactions = useQuery({
    queryKey: ["transactions"],
    queryFn: fetchTransactions,
    retry: (failureCount, error) => error.message !== UNAUTHORIZED && failureCount < 3,
  });

  if (transactions.isPending) {
    return <p role="status">Загрузка операций…</p>;
  }

  if (transactions.isError) {
    if (transactions.error.message === UNAUTHORIZED) {
      return <p role="alert">Запросите новую ссылку командой /login</p>;
    }
    return <p role="alert">Не удалось загрузить операции. Попробуйте ещё раз.</p>;
  }

  if (transactions.data.length === 0) {
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
          {transactions.data.map((transaction) => (
            <tr key={transaction.id}>
              <td>{date.format(new Date(transaction.occurred_at))}</td>
              <td>{transaction.description}</td>
              <td>{rubles.format(transaction.amount_kopecks / 100)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
