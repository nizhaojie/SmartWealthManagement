// 「我的建议」的只读出口与客户决定。未放行的建议在任何客户侧接口都读不到：
// 过滤在服务端（护栏 5 的第二个出口），前端不承担这条边界。
import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import {
  ADVICE_AWAITING,
  type AdviceDecision,
  type AdviceStatus,
  type OperationAdvice,
} from "./types";

/**
 * 本人已送达的建议一页（送达时间倒序）。
 *
 * `status` 是可选的过滤，只有侧栏角标那一路会传它：角标要的是「待决定共几条」，而
 * 列表本身是混合状态的（待决定与三个终态在同一个列表里、由页面按状态现分组），
 * 分页之后本页条数不再等于全局条数。它读的是同一个接口的过滤后 `total`，不是另加
 * 一个 count 接口——两个口径迟早漂移，而「角标说 3、点进去是 2」正是提醒失效的形态。
 */
export function listMyAdvice(
  query: PageQuery & { status?: AdviceStatus },
): Promise<Paginated<OperationAdvice>> {
  const search = queryString({
    page: query.page,
    page_size: query.page_size,
    status: query.status,
  });
  return http.get<Paginated<OperationAdvice>>(`/api/customer/operation-advice${search}`);
}

/**
 * 待客户决定的建议总数。
 *
 * 只取总数，因此页长给 1：要的是 `total`，不是那一条。
 */
export async function countAwaitingAdvice(): Promise<number> {
  const page = await listMyAdvice({
    page: 1,
    page_size: 1,
    status: ADVICE_AWAITING,
  });
  return page.total;
}

/**
 * 做出接受或拒绝。接受是一次原子操作：受理校验不过就整体失败、建议留在待客户决定，
 * 失败语义是受理侧原文透传（`message` 直接渲染）。
 */
export function decideAdvice(
  adviceId: number,
  decision: AdviceDecision,
): Promise<OperationAdvice> {
  return http.post<OperationAdvice>(
    `/api/customer/operation-advice/${encodeURIComponent(adviceId)}/decision`,
    { decision },
  );
}
