import { ApiError } from "@wealth/shared";

// 时间形态由 shared 统一：`YYYY-MM-DD HH:mm:ss`。
export { formatDateTime } from "@wealth/shared";

/** 风险承受等级的呈现文案：`C1`–`C5` 是规范写法，中文只是它在界面上的说法。 */
export const GRADE_LABELS: Record<string, string> = {
  C1: "保守型",
  C2: "稳健型",
  C3: "平衡型",
  C4: "进取型",
  C5: "激进型",
};

export function gradeCaption(level: string | null | undefined): string {
  if (!level) return "未评测";
  const label = GRADE_LABELS[level];
  return label ? `${level} ${label}` : level;
}

/** 标签值的呈现：字符串原样，对象/数组摊平成可读文本，不省略也不编造。 */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value === "" ? "—" : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => formatValue(item)).join("、") : "—";
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (!entries.length) return "—";
    return entries.map(([key, item]) => `${key} ${formatValue(item)}`).join(" · ");
  }
  return String(value);
}

export function formatConfidence(confidence: number): string {
  return confidence.toFixed(2);
}

/** 0–100 的百分比：调用方给小数（0.86 → 86）。 */
export function toPercent(value: number): number {
  return Math.round(value * 100);
}

/** 金额：原型给的是字符串小数，界面上保留两位并挂千分位。 */
export function formatMoney(value: string | number): string {
  const amount = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(amount)) return String(value);
  return amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * 后端给的是它自己写下的那句话，直接透传；只有拿不到消息时（网络断了）才用兜底文案——
 * 用一句写死的话盖过后端的具体原因，等于把可诊断的信息丢掉。
 */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : fallback;
}
