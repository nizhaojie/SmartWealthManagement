// 投顾内容的客户侧出口：把「我想要一份建议」变成一条待审核的投顾内容，
// 以及把顾问放行后的方案（客户送达视图）取回来。
//
// 这里没有 `getAdvisoryPlan`（`GET /api/customer/advisory/plan`，只给最新一份）：
// 客户侧要的是「能看到以前收到的方案」，列表接口覆盖了它。三者共用同一个
// 服务端序列化函数，冲突时以接口为准。
import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type { ProductFilters } from "../products/types";
import type { AdvisoryRequest, ReleasedPlan } from "./types";

export function submitAdvisoryRequest(filters: ProductFilters): Promise<AdvisoryRequest> {
  return http.post<AdvisoryRequest>("/api/customer/advisory-requests", filters);
}

/** 自己提交过的方案请求一页，最近提交的在前。 */
export function listAdvisoryRequests(query: PageQuery): Promise<Paginated<AdvisoryRequest>> {
  const search = queryString({ page: query.page, page_size: query.page_size });
  return http.get<Paginated<AdvisoryRequest>>(`/api/customer/advisory-requests${search}`);
}

/** 该客户的顾问定稿一页，按放行时间倒序；尚无已放行方案时是空页，不是 404。 */
export function listReleasedPlans(query: PageQuery): Promise<Paginated<ReleasedPlan>> {
  const search = queryString({ page: query.page, page_size: query.page_size });
  return http.get<Paginated<ReleasedPlan>>(`/api/customer/advisory/plans${search}`);
}

/** 一份定稿。不属于当前客户的 id 由服务端回 404（不确认他人资源是否存在）。 */
export function getReleasedPlan(finalId: string | number): Promise<ReleasedPlan> {
  return http.get<ReleasedPlan>(`/api/customer/advisory/plans/${encodeURIComponent(finalId)}`);
}
