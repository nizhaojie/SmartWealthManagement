// 交易受理的四个入口，以及交易流水的读。校验、成交与风控的接入全在服务端（ADR-0018）：
// 这里只把客户填的东西发过去，失败时由调用方按受理侧的原文渲染原因。
import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type {
  AcceptanceResult,
  DepositRequest,
  PurchaseRequest,
  RedemptionRequest,
  TransactionFilters,
  TransactionRecord,
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

/**
 * 交易流水的一页：筛选条件 + 页码一起进查询串。
 *
 * 空条件由 `queryString` 统一去掉（`""` 与 `undefined` 都不发），所以调用方可以把
 * 表单里的原样值直接传进来。分页参数与后端契约同名（ADR-0024），不在这里另起名字。
 */
export function listTransactions(
  filters: TransactionFilters,
  query: PageQuery,
): Promise<Paginated<TransactionRecord>> {
  const search = queryString({
    start_date: filters.start_date ?? undefined,
    end_date: filters.end_date ?? undefined,
    transaction_type: filters.transaction_type,
    page: query.page,
    page_size: query.page_size,
  });
  return http.get<Paginated<TransactionRecord>>(`/api/customer/transactions${search}`);
}
