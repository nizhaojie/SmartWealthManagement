import type { ProductFilters } from "../products/types";

/**
 * 方案请求：客户提交「我想要一份建议」之后留下的那条记录。
 * 不含 `customer_id`——客户由令牌圈定，客户侧响应不回显内部标识。
 */
export type AdvisoryRequest = {
  id: number;
  request_no: string;
  status: string;
  filters: ProductFilters;
  submitted_at: string;
};

export type AdvisoryRequestList = {
  requests: AdvisoryRequest[];
};

/**
 * 客户送达视图里的产品要素：客观已披露的那几项。
 *
 * 它是一个独立类型，不与内部端的 `AdvisoryCandidate` 合流——综合得分、
 * 排序依据与推荐理由不在客户可见视图以内（ADR-0016），类型上就不给它们
 * 留位置，免得某天有人顺手 `candidate.score_breakdown` 上屏。
 */
export type ReleasedPlanProduct = {
  product_code: string;
  product_name: string;
  product_type: string;
  risk_level: string;
  expected_return: string;
  term_days: number;
};

/**
 * 客户送达视图：顾问定稿里允许客户看到的那部分（对齐服务端的
 * `serialize_final_for_customer`）。定稿本身完整保留，审核与举证看定稿，
 * 客户看这份。
 */
export type ReleasedPlan = {
  id: number;
  advisor_name: string | null;
  candidates: ReleasedPlanProduct[];
  allocation_suggestion: Record<string, number>;
  released_at: string;
  disclaimer: string | null;
};

export type ReleasedPlanList = {
  plans: ReleasedPlan[];
};
