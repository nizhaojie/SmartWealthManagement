export type ScoreBreakdownItem = {
  dimension: string;
  raw_value: string;
  score: number;
  weight: number;
  contribution: number;
};

export type AdvisoryCandidate = {
  product_code: string;
  product_name: string;
  product_type: string;
  risk_level: string;
  expected_return: string;
  term_days: number;
  composite_score: number;
  score_breakdown: ScoreBreakdownItem[];
  reason: string;
};

/** 审核时在编辑版本上勾选的候选：去掉勾的不会进放行请求。 */
export type EditableCandidate = AdvisoryCandidate & { included: boolean };

export type AdvisoryWarning = {
  code: string;
  message: string;
};

export type AdvisoryDraft = {
  id: number;
  customer_id: number;
  advisor_id: number;
  tilt: string;
  content_classification: string;
  candidates: AdvisoryCandidate[];
  allocation_suggestion: Record<string, number>;
  warnings: AdvisoryWarning[];
  profile_computed_at: string;
  candidate_pool_snapshot: Record<string, unknown>;
  generated_at: string;
  advisory_request_id: number | null;
  disclaimer: string;
};

/**
 * 审核流水线上一条内容的状态。两类内容共用同一条流水线（ADR-0020），取值因此只有
 * 一份：在这里定义，别处引用——同一个状态集写两遍，改状态集时总有一处会漏。
 */
export const REVIEW_STATUSES = ["待审", "处理中", "已放行", "已驳回"] as const;
export type ReviewStatus = (typeof REVIEW_STATUSES)[number];

export type AdvisoryReviewStatus = {
  draft_id: number;
  status: ReviewStatus;
};

/**
 * 审核流水线上的两类内容（ADR-0020）。队列与历史按类型无关地合并它们，每条带类型
 * 标注；载荷长什么样是各类内容自己的事——方案有候选池与配置建议，操作建议只有
 * 「一个产品、一个方向、一个金额、一条理由」。
 */
export const CONTENT_TYPE_PLAN = "方案";
export const CONTENT_TYPE_OPERATION_ADVICE = "操作建议";
export type ContentType = typeof CONTENT_TYPE_PLAN | typeof CONTENT_TYPE_OPERATION_ADVICE;

export type AdvisoryFinal = {
  id: number;
  draft_id: number;
  customer_id: number;
  advisor_id: number;
  advisor_name: string | null;
  content_classification: string;
  candidates: AdvisoryCandidate[];
  allocation_suggestion: Record<string, number>;
  warnings: AdvisoryWarning[];
  released_at: string;
  disclaimer: string;
};

export type PendingRequest = {
  id: number;
  request_no: string;
  customer_id: number;
  customer_name: string;
  filters: Record<string, string>;
  submitted_at: string;
  waiting_seconds: number;
};

/**
 * 待审的一行。`content_ref` 是打开它的地址（方案的 `draft_id` 与操作建议的
 * `advice_id` 各是一套寻址空间，所以不能合成一个字段）；摘要字段按类型出现：
 * 方案是 `tilt`，操作建议是产品、方向与金额。队列里只有标识的那一行没人能用。
 */
export type PendingReview = {
  content_type: ContentType;
  content_ref: number;
  draft_id?: number;
  customer_id: number;
  customer_name: string;
  status: string;
  generated_at: string;
  waiting_seconds: number;
  // 方案特有
  tilt?: string;
  // 操作建议特有
  product_code?: string;
  product_name?: string | null;
  direction?: string;
  amount?: string;
};

export type AdvisoryQueue = {
  pending_requests: PendingRequest[];
  pending_reviews: PendingReview[];
};

export type AdvisoryHistoryEntry = {
  content_type: ContentType;
  content_ref: number;
  draft_id?: number;
  customer_id: number;
  customer_name: string;
  action: "放行" | "驳回";
  reason: string | null;
  decided_at: string;
};

export type AdvisoryComment = {
  id: number;
  review_id: number;
  author_id: number;
  author_name: string | null;
  author_role: string;
  body: string;
  created_at: string;
};
