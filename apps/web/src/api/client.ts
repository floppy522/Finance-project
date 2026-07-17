export type TransactionType = "expense" | "income" | "saving";
export type TransactionDirection = "normal" | "reversal";

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
}

export const UNAUTHORIZED = "UNAUTHORIZED";
export const REQUEST_FAILED = "REQUEST_FAILED";

export async function exchangeLoginToken(token: string): Promise<void> {
  const response = await fetch("/api/auth/exchange", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });

  if (!response.ok) {
    throw new Error(response.status === 401 ? UNAUTHORIZED : REQUEST_FAILED);
  }
}

export async function fetchTransactions(): Promise<TransactionResponse[]> {
  const response = await fetch("/api/transactions", { credentials: "include" });

  if (response.status === 401) {
    throw new Error(UNAUTHORIZED);
  }
  if (!response.ok) {
    throw new Error(REQUEST_FAILED);
  }

  return response.json() as Promise<TransactionResponse[]>;
}
