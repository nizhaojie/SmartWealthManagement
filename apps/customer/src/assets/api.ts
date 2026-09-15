import { http } from "../api/http";
import type { CustomerAssets, LookThrough, TransactionFilters, TransactionList } from "./types";

function queryString(filters: TransactionFilters): string {
  const params = new URLSearchParams();
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  if (filters.transaction_type) params.set("transaction_type", filters.transaction_type);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function getAssets(): Promise<CustomerAssets> {
  return http.get<CustomerAssets>("/api/customer/assets");
}

export function getHoldingLookThrough(productCode: string): Promise<LookThrough> {
  const path = `/api/customer/assets/holdings/${encodeURIComponent(productCode)}/look-through`;
  return http.get<LookThrough>(path);
}

export function listTransactions(filters: TransactionFilters = {}): Promise<TransactionList> {
  return http.get<TransactionList>(`/api/customer/assets/transactions${queryString(filters)}`);
}
