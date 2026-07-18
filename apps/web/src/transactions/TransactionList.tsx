import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  fetchCategories,
  fetchCurrentUser,
  fetchTransactions,
  UNAUTHORIZED,
  updateTransactionCategory,
  type CategoryResponse,
  type TransactionFilters,
} from "../api/client";

const rubles = new Intl.NumberFormat("ru-RU", {
  style: "currency",
  currency: "RUB",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const retryRequest = (failureCount: number, error: Error) =>
  error.message !== UNAUTHORIZED && failureCount < 3;

export function TransactionList() {
  const queryClient = useQueryClient();
  const editInFlight = useRef(false);
  const [categoryCode, setCategoryCode] = useState("");
  const [reviewFilter, setReviewFilter] = useState<"" | "true">("");

  const filters: TransactionFilters = {
    categoryCode: categoryCode || undefined,
    needsCategoryReview: reviewFilter === "true" ? true : undefined,
  };

  const transactions = useQuery({
    queryKey: [
      "transactions",
      filters.categoryCode ?? null,
      filters.needsCategoryReview ?? null,
    ],
    queryFn: () => fetchTransactions(filters),
    retry: retryRequest,
  });

  const owner = useQuery({
    queryKey: ["current-user"],
    queryFn: fetchCurrentUser,
    retry: retryRequest,
  });

  const categories = useQuery({
    queryKey: ["categories"],
    queryFn: async () => {
      const catalogs = await Promise.all([
        fetchCategories("expense"),
        fetchCategories("income"),
      ]);
      return catalogs.flat();
    },
    retry: retryRequest,
  });

  const categoryMutation = useMutation({
    mutationFn: ({ id, nextCategoryCode }: { id: string; nextCategoryCode: string }) =>
      updateTransactionCategory(id, nextCategoryCode),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["transactions"] }),
        queryClient.invalidateQueries({ queryKey: ["categories"] }),
      ]);
    },
    onSettled: () => {
      editInFlight.current = false;
    },
  });

  const queries = [transactions, owner, categories];
  const queryError = queries.find((query) => query.isError)?.error;
  if (queryError) {
    if (queryError.message === UNAUTHORIZED) {
      return <p role="alert">Запросите новую ссылку командой /login</p>;
    }
    return <p role="alert">Не удалось загрузить операции. Попробуйте ещё раз.</p>;
  }

  if (owner.isPending || categories.isPending) {
    return <p role="status">Загрузка операций…</p>;
  }

  const transactionData = transactions.data ?? [];
  const ownerData = owner.data!;
  const categoryData = categories.data ?? [];
  const hasSelectedFilters = categoryCode !== "" || reviewFilter !== "";
  const resultsPending = transactions.isPending || transactions.isPlaceholderData;
  const descriptionCounts = new Map<string, number>();
  const descriptionOrdinals = new Map<string, number>();
  const categoryLabels = new Map<string, string>();

  for (const transaction of transactionData) {
    descriptionCounts.set(
      transaction.description,
      (descriptionCounts.get(transaction.description) ?? 0) + 1,
    );
  }
  for (const transaction of transactionData) {
    const total = descriptionCounts.get(transaction.description) ?? 1;
    const ordinal = (descriptionOrdinals.get(transaction.description) ?? 0) + 1;
    descriptionOrdinals.set(transaction.description, ordinal);
    categoryLabels.set(
      transaction.id,
      total === 1
        ? `Категория: ${transaction.description}`
        : `Категория: ${transaction.description}, операция ${ordinal} из ${total}`,
    );
  }

  const updateCategory = (id: string, nextCategoryCode: string) => {
    if (editInFlight.current || categoryMutation.isPending) return;

    editInFlight.current = true;
    categoryMutation.reset();
    categoryMutation.mutate({ id, nextCategoryCode });
  };

  return (
    <section aria-labelledby="transactions-title">
      <h2 id="transactions-title" className="visually-hidden">
        Операции
      </h2>

      <div className="transaction-filters" aria-label="Фильтры операций">
        <label>
          <span>Категория</span>
          <select
            aria-label="Фильтр по категории"
            value={categoryCode}
            onChange={(event) => setCategoryCode(event.target.value)}
          >
            <option value="">Все категории</option>
            <optgroup label="Расходы">
              {categoryData
                .filter((category) => category.transaction_type === "expense")
                .map((category) => (
                  <option key={category.code} value={category.code}>
                    {category.name_ru}
                  </option>
                ))}
            </optgroup>
            <optgroup label="Доходы">
              {categoryData
                .filter((category) => category.transaction_type === "income")
                .map((category) => (
                  <option key={category.code} value={category.code}>
                    {category.name_ru}
                  </option>
                ))}
            </optgroup>
          </select>
        </label>

        <label>
          <span>Проверка</span>
          <select
            aria-label="Фильтр проверки"
            value={reviewFilter}
            onChange={(event) => setReviewFilter(event.target.value as "" | "true")}
          >
            <option value="">Все</option>
            <option value="true">Требуют проверки</option>
          </select>
        </label>
      </div>

      {categoryMutation.isError && (
        <p role="alert" className="inline-error">
          {categoryMutation.error.message === UNAUTHORIZED
            ? "Запросите новую ссылку командой /login"
            : "Не удалось изменить категорию. Попробуйте ещё раз."}
        </p>
      )}

      {resultsPending ? (
        <p role="status">Загрузка операций…</p>
      ) : transactionData.length === 0 ? (
        <p>
          {hasSelectedFilters
            ? "По выбранным фильтрам операций нет."
            : "Операций пока нет."}
        </p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption>Операции</caption>
            <thead>
              <tr>
                <th scope="col">Дата</th>
                <th scope="col">Описание</th>
                <th scope="col">Категория</th>
                <th scope="col">Сумма</th>
              </tr>
            </thead>
            <tbody>
              {transactionData.map((transaction) => {
                const compatibleCategories = categoryData.filter(
                  (category): category is CategoryResponse =>
                    category.transaction_type === transaction.transaction_type,
                );

                return (
                  <tr key={transaction.id}>
                    <td>
                      {new Intl.DateTimeFormat("ru-RU", {
                        dateStyle: "medium",
                        timeZone: ownerData.timezone,
                      }).format(new Date(transaction.occurred_at))}
                    </td>
                    <td>{transaction.description}</td>
                    <td>
                      {compatibleCategories.length > 0 ? (
                        <div className="category-cell">
                          <select
                            className="category-badge"
                            aria-label={categoryLabels.get(transaction.id)}
                            value={transaction.category_code ?? ""}
                            disabled={categoryMutation.isPending}
                            onChange={(event) =>
                              updateCategory(transaction.id, event.target.value)
                            }
                          >
                            {transaction.category_code === null && (
                              <option value="" disabled>
                                Без категории
                              </option>
                            )}
                            {compatibleCategories.map((category) => (
                              <option key={category.code} value={category.code}>
                                {category.name_ru}
                              </option>
                            ))}
                          </select>
                          {transaction.needs_category_review && (
                            <span className="review-badge">
                              <span aria-hidden="true">Проверьте</span>
                              <span className="visually-hidden">
                                Категория требует проверки
                              </span>
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="category-empty">Без категории</span>
                      )}
                    </td>
                    <td>{rubles.format(transaction.amount_kopecks / 100)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
