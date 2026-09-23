import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type { AdvisoryComment } from "../advisory/types";
import type {
  AdviceOptions,
  AdviceReviewStatus,
  OperationAdvice,
  OperationAdviceProgress,
} from "./types";

/**
 * 操作建议的内部接口。
 *
 * 读取这一侧与方案同一条口径：理财顾问不受限，客户经理只能看自己名下客户的；
 * 放行与驳回只对理财顾问开放（后端按角色再挡一次，前端只是不给入口）。
 */

/** 这位客户的建议进度一页（最近发起的在前）。 */
export function listCustomerAdvice(
  customerId: number,
  query: PageQuery,
): Promise<Paginated<OperationAdviceProgress>> {
  const search = queryString({ page: query.page, page_size: query.page_size });
  return http.get<Paginated<OperationAdviceProgress>>(
    `/api/internal/customers/${customerId}/operation-advice${search}`,
  );
}

/**
 * 发起前要看得见的东西：这位客户在这个方向下能选哪些产品、每只的区间是多少。
 * 产品与金额 / 份额由发起人选定（ADR-0021），可选项由后端算好——前端只读只渲染。
 */
export function listAdviceOptions(
  customerId: number,
  direction: string,
): Promise<AdviceOptions> {
  return http.get<AdviceOptions>(
    `/api/internal/customers/${customerId}/operation-advice-options?direction=${encodeURIComponent(direction)}`,
  );
}

/**
 * 发起建议：产品与金额（申购）/ 份额（赎回）由发起人填，与客户侧自助交易同口径。
 * `quantity` 按方向落在 `amount` 或 `shares` 上，另一个字段不出现。
 */
export function startAdvice(
  customerId: number,
  direction: string,
  productCode: string,
  quantity: string,
): Promise<OperationAdvice> {
  const body =
    direction === "申购"
      ? { direction, product_code: productCode, amount: quantity }
      : { direction, product_code: productCode, shares: quantity };
  return http.post<OperationAdvice>(
    `/api/internal/customers/${customerId}/operation-advice`,
    body,
  );
}

export function getAdvice(adviceId: number): Promise<OperationAdvice> {
  return http.get<OperationAdvice>(`/api/internal/operation-advice/${adviceId}`);
}

export function getAdviceReview(adviceId: number): Promise<AdviceReviewStatus> {
  return http.get<AdviceReviewStatus>(`/api/internal/operation-advice/${adviceId}/review`);
}

export function listAdviceComments(adviceId: number): Promise<AdvisoryComment[]> {
  return http
    .get<{ comments: AdvisoryComment[] }>(
      `/api/internal/operation-advice/${adviceId}/comments`,
    )
    .then((data) => data.comments);
}

export function postAdviceComment(adviceId: number, body: string): Promise<AdvisoryComment> {
  return http.post<AdvisoryComment>(`/api/internal/operation-advice/${adviceId}/comments`, {
    body,
  });
}

export function releaseAdvice(adviceId: number): Promise<{ id: number; status: string }> {
  // 操作建议放行不产生第二份载荷（#06）：它没有候选池、也没有可编辑的字段，
  // 审核记录上的「已放行」本身就是送达依据。
  return http.post<{ id: number; status: string }>(
    `/api/internal/operation-advice/${adviceId}/release`,
    {},
  );
}

export function rejectAdvice(
  adviceId: number,
  reason: string,
): Promise<{ id: number; status: string; reason: string }> {
  return http.post(`/api/internal/operation-advice/${adviceId}/reject`, { reason });
}
