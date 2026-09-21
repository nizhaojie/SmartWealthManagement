/**
 * 操作建议在客户侧的状态（CONTEXT「客户决定」）：
 *
 *     待客户决定 → 已接受 / 已拒绝 / 已过期
 *
 * 三个终态都是事实陈述，不是流程节点——已接受 / 已拒绝来自一条客户决定记录，
 * 已过期是「送达满 7 个自然日而没有作答」这件时间的事实。状态由服务端现算，前端不推导。
 */
export const ADVICE_AWAITING = "待客户决定";
export const ADVICE_ACCEPTED = "已接受";
export const ADVICE_REJECTED = "已拒绝";
export const ADVICE_EXPIRED = "已过期";

export const ADVICE_STATUSES = [
  ADVICE_AWAITING,
  ADVICE_ACCEPTED,
  ADVICE_REJECTED,
  ADVICE_EXPIRED,
] as const;

export type AdviceStatus = (typeof ADVICE_STATUSES)[number];

/** 客户对一条建议的决定：接受当场成交，拒绝只留一条记录。 */
export const DECISION_ACCEPT = "接受";
export const DECISION_REJECT = "拒绝";

export type AdviceDecision = typeof DECISION_ACCEPT | typeof DECISION_REJECT;

/**
 * 操作建议的方向。一次只对应一个产品一个方向（Q9 的硬边界）——同一个动作序列套到
 * 两只产品上就是配置方案，那是投顾助手的地盘。
 */
export const ADVICE_DIRECTIONS = ["申购", "赎回"] as const;

export type AdviceDirection = (typeof ADVICE_DIRECTIONS)[number];

/**
 * 一条已送达的操作建议 = 客户送达视图里的那部分（服务端逐项拣选，ADR-0016）：
 * 建议本身的四件事（产品、方向、金额、理由）加上状态、时限与决定结果。
 * 发起人（客户经理）、内容分类、客户标识不在其中——它们不在这里留位置。
 */
export type OperationAdvice = {
  id: number;
  product_code: string;
  product_name: string | null;
  direction: AdviceDirection;
  amount: string;
  reason: string;
  status: AdviceStatus;
  released_at: string;
  expires_at: string;
  decision: AdviceDecision | null;
  decided_at: string | null;
  disclaimer: string | null;
};

export type OperationAdviceList = {
  advice: OperationAdvice[];
};
