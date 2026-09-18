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

export type AdvisoryReviewStatus = {
  draft_id: number;
  status: "待审" | "处理中" | "已放行" | "已驳回";
};

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

export type PendingReview = {
  draft_id: number;
  customer_id: number;
  customer_name: string;
  status: string;
  tilt: string;
  generated_at: string;
  waiting_seconds: number;
};

export type AdvisoryQueue = {
  pending_requests: PendingRequest[];
  pending_reviews: PendingReview[];
};

export type AdvisoryHistoryEntry = {
  draft_id: number;
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
