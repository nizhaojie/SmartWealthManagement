import type { RiskLevel } from "../risk-assessment/types";

/**
 * 产品风险等级：R1 到 R5。它与风险承受等级（C1–C5）是两套独立的刻度，
 * 只在适当性匹配时发生比较——这个常量的唯一出处，筛选控件与资产页的分布图都用它。
 */
export const PRODUCT_RISK_LEVELS = ["R1", "R2", "R3", "R4", "R5"] as const;

export type ProductRiskLevel = (typeof PRODUCT_RISK_LEVELS)[number];

export type Product = {
  product_code: string;
  product_name: string;
  product_type: string;
  risk_level: string;
  expected_return: string;
  min_amount: string;
  term_days: number;
  fund_manager: string | null;
  fee_rate: string;
  status: string;
};

/**
 * 筛选条件只允许客观已披露要素。不提供「适合我的」「推荐指数」一类条件——
 * 那属于投顾内容，不是事实性内容（ADR-0005）。
 */
export type ProductFilters = {
  product_type?: string;
  risk_level?: string;
  min_amount?: string;
  min_expected_return?: string;
  max_term_days?: string;
};

export type ProductList = {
  products: Product[];
};

/** 适当性硬过滤的结果：客户的风险承受等级，以及由此可购买的产品风险等级范围。 */
export type CandidatePool = {
  assessment_id: number;
  customer_risk_level: RiskLevel;
  allowed_product_risk_levels: string[];
  products: { product_code: string; product_name: string; product_type: string; risk_level: string }[];
};
