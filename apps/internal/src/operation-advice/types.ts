import type { ReviewStatus } from "../advisory/types";

export type { ReviewStatus };

/**
 * 操作建议的内部视图。
 *
 * 载荷只有「一个产品、一个方向、一个金额、一条理由」（ADR-0020）：候选池快照、
 * 配置建议、画像警示是配置方案特有的，这里一个字段都不带。审核页与发起进度读的是
 * 同一份载荷，因此两处看到的是同一件事。
 *
 * 审核状态不在这里定义：两类内容共用同一条流水线，取值属于流水线（`advisory/types`）。
 */
export const DIRECTIONS = ["申购", "赎回"] as const;
export type Direction = (typeof DIRECTIONS)[number];

/** 已放行之后才有的客户侧状态（`app.operation_advice.decision`）。 */
export const CUSTOMER_STATUSES = ["待客户决定", "已接受", "已拒绝", "已过期"] as const;
export type CustomerStatus = (typeof CUSTOMER_STATUSES)[number];

export type OperationAdvice = {
  id: number;
  customer_id: number;
  manager_id: number;
  product_code: string;
  /** 产品不在目录里时为 null：少一个名字，不让这条建议整行消失。 */
  product_name: string | null;
  direction: Direction;
  amount: string;
  reason: string;
  content_classification: string;
  generated_at: string;
  disclaimer: string;
};

/** 客户经理看到的进度：审核进度是一列，客户决定是另一列（未放行时为空）。 */
export type OperationAdviceProgress = {
  id: number;
  product_code: string;
  product_name: string | null;
  direction: Direction;
  amount: string;
  reason: string;
  review_status: ReviewStatus;
  customer_status: CustomerStatus | null;
  generated_at: string;
};

export type AdviceReviewStatus = {
  advice_id: number;
  status: ReviewStatus;
};

/**
 * 发起前可选项的一只产品（`GET .../operation-advice-options`）：方向过滤 + 金额/份额
 * 区间 + 后端算好的 `affordable`。前端只读、只渲染，不按方向过滤、不算买不买得起
 * （ADR-0021 的主要实现约束）。
 */
export type AdviceOption = {
  product_code: string;
  product_name: string;
  product_type: string;
  risk_level: string;
  term_days: number;
  min_amount: string;
  /** 申购方向：可用余额买得起的最大金额（赎回方向不出现这一项）。 */
  max_amount?: string;
  /** 赎回方向：可赎回份额，即当前持仓份额（申购方向不出现这一项）。 */
  max_shares?: string;
  /** 后端算好的布尔：买不买得起（赎回恒为真）。 */
  affordable: boolean;
};

export type AdviceOptions = {
  direction: Direction;
  products: AdviceOption[];
};
