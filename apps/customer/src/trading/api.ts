// 交易受理的三个入口。校验、成交与风控的接入全在服务端（ADR-0018）：
// 这里只把客户填的东西发过去，失败时由调用方按受理侧的原文渲染原因。
import { http } from "../api/http";
import type {
  AcceptanceResult,
  PurchaseRequest,
  RedemptionRequest,
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
