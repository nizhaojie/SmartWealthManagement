import { ADVISOR, type EmployeeRole } from "../auth/identity";
import type { AdvisoryCandidate, AdvisoryReviewStatus, EditableCandidate } from "./types";

/** 只有理财顾问能放行或驳回；客户经理可以查看与留言。 */
export function canReview(role: EmployeeRole | undefined): boolean {
  return role === ADVISOR;
}

export type ReviewDecision = AdvisoryReviewStatus["status"];

export function isDecided(status: ReviewDecision | undefined): boolean {
  return status === "已放行" || status === "已驳回";
}

/**
 * 放行请求里的候选：只带勾选的，并且剥掉前端专用的 `included` 标记——
 * 后端存的是顾问定稿本身，不该多一个界面状态的字段。
 */
export function toCandidatePayload(list: readonly EditableCandidate[]): AdvisoryCandidate[] {
  const payload: AdvisoryCandidate[] = [];
  for (const item of list) {
    if (!item.included) continue;
    const candidate = { ...item };
    delete (candidate as Partial<EditableCandidate>).included;
    payload.push(candidate);
  }
  return payload;
}
