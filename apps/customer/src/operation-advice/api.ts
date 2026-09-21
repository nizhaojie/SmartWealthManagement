// 「我的建议」的只读出口与客户决定。未放行的建议在任何客户侧接口都读不到：
// 过滤在服务端（护栏 5 的第二个出口），前端不承担这条边界。
import { http } from "../api/http";
import type { AdviceDecision, OperationAdvice, OperationAdviceList } from "./types";

/** 本人已送达的建议：待决定的与已决定的都在同一个列表里，按送达时间倒序。 */
export function listMyAdvice(): Promise<OperationAdviceList> {
  return http.get<OperationAdviceList>("/api/customer/operation-advice");
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
