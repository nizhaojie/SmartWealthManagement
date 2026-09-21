import { ApiError } from "@wealth/shared";

/**
 * 受理侧拒绝时的原文里，只有「未测评」这一条是客户自己就能解决的——去风险测评就够了。
 * 它回的是固定文案（服务端的 `app.order_acceptance.service.ASSESSMENT_REQUIRED_MESSAGE`），
 * 因此只能按文案相等判定：越级也是 403，越级与未测评光看状态码分不开。
 *
 * 这是前端对服务端文案的一处硬依赖，与 `advisory` 侧按状态码分派是同一价位；
 * 服务端改这句话时，这里会跟着失效（不会报错，只是不再给出测评入口）。
 */
export const ASSESSMENT_REQUIRED_MESSAGE = "请先完成风险测评";

/** 一次受理失败在界面上要渲染的两样东西。 */
export type AcceptanceFailure = {
  /** 受理侧的原文透传（余额不足带「还差多少」、越级是风险等级、未测评是那句提示）。 */
  message: string;
  /** 客户能自己解决的那一条：界面上要同时给出「去风险测评」的入口。 */
  assessmentRequired: boolean;
};

/**
 * 把受理失败翻成界面要渲染的东西。非 ApiError（网络断掉、解析失败）时才用兜底话术——
 * 受理侧的拒绝文案是给客户的，不要被一句泛泛的「操作失败」盖掉。
 */
export function describeAcceptanceFailure(error: unknown, fallback: string): AcceptanceFailure {
  if (!(error instanceof ApiError)) {
    return { message: fallback, assessmentRequired: false };
  }
  return {
    message: error.message,
    assessmentRequired: error.message === ASSESSMENT_REQUIRED_MESSAGE,
  };
}
