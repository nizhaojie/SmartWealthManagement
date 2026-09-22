// 交易受理的四个入口，以及交易流水的读。校验、成交与风控的接入全在服务端（ADR-0018）：
// 这里只把客户填的东西发过去，失败时由调用方按受理侧的原文渲染原因。
import { http } from "../api/http";
import type {
  AcceptanceResult,
  DepositRequest,
  PurchaseRequest,
  RedemptionRequest,
  TransactionFilters,
  TransactionList,
  TransferRequest,
} from "./types";

export function purchase(request: PurchaseRequest): Promise<AcceptanceResult> {
  return http.post<AcceptanceResult>("/api/customer/transactions/purchase", request);
}

export function redeem(request: RedemptionRequest): Promise<AcceptanceResult> {
  return http.post<AcceptanceResult>("/api/customer/transactions/redemption", request);
}

export function transfer(request: TransferRequest): Promise<AcceptanceResult> {
  return http.post<AcceptanceResult>("/api/customer/transactions/transfer", request);
}

export function deposit(request: DepositRequest): Promise<AcceptanceResult> {
  return http.post<AcceptanceResult>("/api/customer/transactions/deposit", request);
}

function queryString(filters: TransactionFilters): string {
  const params = new URLSearchParams();
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  if (filters.transaction_type) params.set("transaction_type", filters.transaction_type);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function listTransactions(filters: TransactionFilters = {}): Promise<TransactionList> {
  return http.get<TransactionList>(`/api/customer/transactions${queryString(filters)}`);
}
