import { ADVISOR, type EmployeeRole } from "../auth/identity";
import { formatMoney } from "../format";
import {
  CONTENT_TYPE_OPERATION_ADVICE,
  type AdvisoryCandidate,
  type ContentType,
  type EditableCandidate,
  type PendingReview,
  type ReviewStatus,
} from "./types";

/** 只有理财顾问能放行或驳回；客户经理可以查看与留言。 */
export function canReview(role: EmployeeRole | undefined): boolean {
  return role === ADVISOR;
}

export function isDecided(status: ReviewStatus | undefined): boolean {
  return status === "已放行" || status === "已驳回";
}

/**
 * 打开一行待审 / 已决定的内容：**跳哪一张审核页由内容类型决定**。
 *
 * 两类内容共用同一条流水线（ADR-0020），但载荷不同，因此各有自己的渲染页。
 * 把类型判断写在这里而不是散在模板里：模板里写错一个 if 只是跳到一个渲染空字段的
 * 页面上，两处都看起来「正常」。
 */
export type ReviewTarget =
  | { name: "advisory-review"; params: { draftId: number } }
  | { name: "operation-advice-review"; params: { adviceId: number } };

export function reviewTarget(contentType: ContentType, contentRef: number): ReviewTarget {
  if (contentType === CONTENT_TYPE_OPERATION_ADVICE) {
    return { name: "operation-advice-review", params: { adviceId: contentRef } };
  }
  return { name: "advisory-review", params: { draftId: contentRef } };
}

/**
 * 队列里那一列摘要：方案说的是生成侧重，操作建议说的是「哪个产品、什么方向、
 * 多少钱」。两类内容在这里说的不是同一件事，所以各给各的说法，不硬凑成一列同义词。
 */
export function reviewSummaryLabel(row: PendingReview): string {
  if (row.content_type === CONTENT_TYPE_OPERATION_ADVICE) {
    const product = row.product_name ?? row.product_code ?? "—";
    const amount = row.amount ? formatMoney(row.amount) : "—";
    return `${product} · ${row.direction ?? "—"} · ${amount}`;
  }
  return row.tilt ?? "—";
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
