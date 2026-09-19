// 投顾内容的客户侧出口：把「我想要一份建议」变成一条待审核的投顾内容，
// 以及把顾问放行后的方案（客户送达视图）取回来。
//
// 这里没有 `getAdvisoryPlan`（`GET /api/customer/advisory/plan`，只给最新一份）：
// 客户侧要的是「能看到以前收到的方案」，列表接口覆盖了它。三者共用同一个
// 服务端序列化函数，冲突时以接口为准。
import { http } from "../api/http";
import type { ProductFilters } from "../products/types";
import type {
  AdvisoryRequest,
  AdvisoryRequestList,
  ReleasedPlan,
  ReleasedPlanList,
} from "./types";

export function submitAdvisoryRequest(filters: ProductFilters): Promise<AdvisoryRequest> {
  return http.post<AdvisoryRequest>("/api/customer/advisory-requests", filters);
}

export function listAdvisoryRequests(): Promise<AdvisoryRequestList> {
  return http.get<AdvisoryRequestList>("/api/customer/advisory-requests");
}

/** 该客户的顾问定稿列表，按放行时间倒序；尚无已放行方案时是空数组，不是 404。 */
export function listReleasedPlans(): Promise<ReleasedPlanList> {
  return http.get<ReleasedPlanList>("/api/customer/advisory/plans");
}

/** 一份定稿。不属于当前客户的 id 由服务端回 404（不确认他人资源是否存在）。 */
export function getReleasedPlan(finalId: string | number): Promise<ReleasedPlan> {
  return http.get<ReleasedPlan>(`/api/customer/advisory/plans/${encodeURIComponent(finalId)}`);
}
