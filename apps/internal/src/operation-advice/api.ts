import { http } from "../api/http";
import type { AdvisoryComment } from "../advisory/types";
import type {
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

export function listCustomerAdvice(customerId: number): Promise<OperationAdviceProgress[]> {
  return http
    .get<{ advice: OperationAdviceProgress[] }>(
      `/api/internal/customers/${customerId}/operation-advice`,
    )
    .then((data) => data.advice);
}

export function startAdvice(customerId: number, direction: string): Promise<OperationAdvice> {
  return http.post<OperationAdvice>(
    `/api/internal/customers/${customerId}/operation-advice`,
    { direction },
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
