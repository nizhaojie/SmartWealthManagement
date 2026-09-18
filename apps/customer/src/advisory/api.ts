// 方案请求：把「我想要一份建议」变成一条待审核的投顾内容。
//
// 注意这里没有 `getAdvisoryPlan`：`GET /api/customer/advisory/plan`（顾问定稿）
// 在本 slice 中仍无前端消费方——客户侧不设「我的方案」页是记录在案的缺口，
// 不是遗漏。要补它需要先回答「客户在什么场景下看、看完留不留痕」。
import { http } from "../api/http";
import type { ProductFilters } from "../products/types";
import type { AdvisoryRequest, AdvisoryRequestList } from "./types";

export function submitAdvisoryRequest(filters: ProductFilters): Promise<AdvisoryRequest> {
  return http.post<AdvisoryRequest>("/api/customer/advisory-requests", filters);
}

export function listAdvisoryRequests(): Promise<AdvisoryRequestList> {
  return http.get<AdvisoryRequestList>("/api/customer/advisory-requests");
}
