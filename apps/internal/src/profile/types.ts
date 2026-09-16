export type ProfileTag = {
  key: string;
  label: string;
  value: unknown;
  source: string;
  confidence: number;
  observed_at: string;
};

export type ConflictRecord = {
  tag_key: string;
  old_value: unknown;
  old_source: string;
  new_value: unknown;
  new_source: string;
  changed_at: string;
  reason: string | null;
};

export type CircuitBreakReason = {
  code: string;
  message: string;
};

export type DimensionScores = {
  基础属性: number;
  投资经验: number;
  风险偏好: number;
  行为异常: number;
};

export type Judgement = {
  circuit_break: boolean;
  reasons: CircuitBreakReason[];
  risk_level: string | null;
  dimension_scores: DimensionScores | null;
  weighted_score: number | null;
};

export type CustomerProfileView = {
  customer_id: number;
  real_name: string;
  computed_at: string;
  tags: ProfileTag[];
  conflict_records: ConflictRecord[];
  judgement: Judgement;
};

export type RiskAssessmentRecord = {
  id: number;
  assessment_date: string;
  risk_level: string;
  total_score: number;
  valid_until: string;
};

export type CustomerListItem = {
  id: number;
  username: string;
  real_name: string;
  customer_level: string;
  risk_level: string | null;
};

export type Holding = {
  product_code: string;
  product_name: string;
  product_type: string;
  product_risk_level: string;
  shares: string;
  cost_amount: string;
  market_value: string;
  profit_loss: string;
  profit_ratio: string;
};

export type CustomerAssets = {
  risk_level: string | null;
  risk_level_valid_until: string | null;
  total_market_value: string;
  holding_count: number;
  holdings: Holding[];
};
