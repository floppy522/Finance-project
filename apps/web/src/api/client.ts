export type TransactionType = "expense" | "income" | "saving";
export type TransactionDirection = "normal" | "reversal";
export type CategorySource = "learned" | "rules" | "ai" | "manual" | "fallback";

/** Mirrors the API's TransactionResponse JSON shape. Monetary values stay in kopecks. */
export interface TransactionResponse {
  id: string;
  owner: number;
  transaction_type: TransactionType;
  direction: TransactionDirection;
  amount_kopecks: number;
  occurred_at: string;
  created_at: string;
  description: string;
  source: string;
  source_event_id: string | null;
  category_code: string | null;
  category_name_ru: string | null;
  category_source: CategorySource | null;
  category_confidence: number | null;
  needs_category_review: boolean | null;
}

export interface CategoryResponse {
  code: string;
  transaction_type: "expense" | "income";
  name_ru: string;
}

export interface TransactionFilters {
  categoryCode?: string;
  needsCategoryReview?: boolean;
}

export interface CurrentUserResponse {
  telegram_user_id: number;
  timezone: string;
}

export const UNAUTHORIZED = "UNAUTHORIZED";
export const REQUEST_FAILED = "REQUEST_FAILED";

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, { ...init, credentials: "include" });

  if (response.status === 401) {
    throw new Error(UNAUTHORIZED);
  }
  if (!response.ok) {
    throw new Error(REQUEST_FAILED);
  }
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function exchangeLoginToken(token: string): Promise<void> {
  await request<void>("/api/auth/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export async function fetchTransactions(
  filters: TransactionFilters = {},
): Promise<TransactionResponse[]> {
  const params = new URLSearchParams();

  if (filters.categoryCode) {
    params.set("category_code", filters.categoryCode);
  }
  if (filters.needsCategoryReview !== undefined) {
    params.set("needs_category_review", String(filters.needsCategoryReview));
  }

  const query = params.toString();
  return request<TransactionResponse[]>(`/api/transactions${query ? `?${query}` : ""}`);
}

export async function fetchCategories(
  transactionType: CategoryResponse["transaction_type"],
): Promise<CategoryResponse[]> {
  const params = new URLSearchParams({ transaction_type: transactionType });
  return request<CategoryResponse[]>(`/api/categories?${params.toString()}`);
}

export async function fetchCurrentUser(): Promise<CurrentUserResponse> {
  return request<CurrentUserResponse>("/api/auth/me");
}

export async function updateTransactionCategory(
  id: string,
  categoryCode: string,
): Promise<TransactionResponse> {
  return request<TransactionResponse>(`/api/transactions/${id}/category`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category_code: categoryCode }),
  });
}
