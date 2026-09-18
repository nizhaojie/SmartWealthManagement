import type { CandidatePool } from "./types";

/** 拿不到可购范围时的说明（未测评 / 测评过期 / 接口不可用三种情形各自有更精确的说法）。 */
export const SUITABILITY_UNAVAILABLE = "尚未完成风险测评，无法确定可购买的产品范围；完成测评后再来筛选。";
export const SUITABILITY_EXPIRED = "您的风险测评已过期，请重新测评后再来筛选产品。";
export const SUITABILITY_UNKNOWN = "暂时无法获取您的可购买产品范围，请稍后重试或联系您的客户经理。";

/**
 * 适当性说明：可购范围由后端硬过滤决定，这里只把它照实说出来。
 * Cn 客户可购买 R1 至 Rn 的产品是法定约束，不是建议。
 */
export function describeSuitability(pool: CandidatePool): string {
  const allowed = pool.allowed_product_risk_levels;
  if (allowed.length === 0) {
    return `您的风险承受等级为 ${pool.customer_risk_level}，当前没有可购买的在售产品范围，请联系您的客户经理。`;
  }
  const range = allowed.length > 1 ? `${allowed[0]}–${allowed[allowed.length - 1]}` : allowed[0];
  return `您的风险承受等级为 ${pool.customer_risk_level}，按适当性匹配只能购买 ${range} 的产品；下方清单已按该范围过滤，越级产品不会出现。`;
}
