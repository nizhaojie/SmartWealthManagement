import type { CustomerProfileView, ProfileTag } from "./types";

/** 低于这个置信度就提示「沟通前请核实来源」。 */
export const LOW_CONFIDENCE = 0.5;

export const DIMENSION_ORDER = ["基础属性", "投资经验", "风险偏好", "行为异常"] as const;

export const TAG_LABELS: Record<string, string> = {
  risk_level: "风险承受等级",
  investment_experience: "投资经验",
  annual_income_range: "收入区间",
  total_assets: "资产规模",
  target_allocation: "目标配置",
  product_preference: "产品偏好",
};

export function tagLabel(tagKey: string): string {
  return TAG_LABELS[tagKey] ?? tagKey;
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * 画像的两条警示：置信度偏低与风险评测过期。
 *
 * 评测过期看两处——熔断原因里已写明，或**最近那次**评测的有效期已过。后者的有效期由
 * 资产接口给（`risk_level_valid_until`）：历次评测分页之后，前端手里的「第一条」只是
 * 某一页的第一条，拿它当最近的一次会在翻页时把这条警示说错。
 */
export function profileWarnings(
  profile: CustomerProfileView,
  riskValidUntil: string | null | undefined,
): string[] {
  const warnings: string[] = [];

  if (profile.tags.some((tag) => tag.confidence < LOW_CONFIDENCE)) {
    warnings.push("部分标签置信度偏低，沟通前请核实来源");
  }

  const expiredByReason = profile.judgement.reasons.some(
    (reason) => reason.code === "ASSESSMENT_EXPIRED",
  );
  const expiredByDate = Boolean(riskValidUntil && riskValidUntil < todayIsoDate());
  if (expiredByReason || expiredByDate) {
    warnings.push("风险评测已过期，请提示客户重新评估");
  }

  return warnings;
}

/**
 * 修正值的解析：原值是对象就按 JSON 读，否则原样当字符串。
 * 解析失败说明输入的不是合法 JSON，此时不猜，直接不提交（由调用方报错）。
 */
export function parseCorrectionValue(raw: string, original: unknown): unknown {
  const trimmed = raw.trim();
  if (original !== null && typeof original === "object") {
    return JSON.parse(trimmed) as unknown;
  }
  return trimmed;
}

/**
 * 画像里的风险承受等级：标签 `risk_level` 的值。
 *
 * 它与 `judgement.risk_level` 不是一个东西——后者是四维度加权研判算出来的等级，用来与
 * 评测结论互为印证，且几乎必然与它不同（王守成：标签 C5，研判加权 59.83 → C3）。界面上
 * 说「C5 激进型」时说的是这个标签：它是适当性匹配的依据，也是历次评测写进来的结论。
 */
export function riskLevelOf(tags: readonly ProfileTag[]): string | null {
  const value = tags.find((item) => item.key === "risk_level")?.value;
  return typeof value === "string" && value ? value : null;
}

export function targetAllocationOf(tags: readonly ProfileTag[]): Record<string, number> | null {
  const tag = tags.find((item) => item.key === "target_allocation");
  if (!tag || tag.value === null || typeof tag.value !== "object") return null;
  return tag.value as Record<string, number>;
}
