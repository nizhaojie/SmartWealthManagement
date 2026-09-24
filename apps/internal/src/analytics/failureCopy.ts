import type { RoundFailure } from "./threadStore";

/**
 * 五种业务码各自的呈现文案。**不是一句「出错了」**：每一种没问成的原因不同，员工据此决定
 * 下一步怎么问（换范围 / 换说法 / 稍后再试），把五种压成一句话等于把这条线索丢了。
 *
 * 文案由码决定，不照抄后端那句话：后端的 message 是写给日志与诊断的（可能带表名、字段名等
 * 内部措辞），呈现面按「码 → 人话」定。原文照样留着另起一行，两边都不丢。
 */
const FAILURE_COPY: Record<number, string> = {
  1101: "超出可查范围：只能问语义视图覆盖的数据（客户、持仓、交易等已脱敏指标）。",
  1102: "无法生成查询：这个问题没能翻译成一句可查的查询。",
  1103: "查询未通过安全校验：这一问没有执行。",
  1104: "查询超时：数据没有在时限内返回。",
  1105: "查询执行失败：查询没能跑完。",
};

export type FailureNotice = {
  /** 由业务码决定的呈现文案；码认不出来时回落成后端写下的那句话。 */
  headline: string;
  /** 后端原文，另起一行留着诊断；已经当呈现文案用时为空。 */
  detail: string | null;
};

export function failureNotice(failure: RoundFailure): FailureNotice {
  const copy = failure.code === null ? undefined : FAILURE_COPY[failure.code];
  if (!copy) {
    // 认不出的码（或连码都没拿到）不编文案：原文照给，总比一句笼统的提示有信息。
    return { headline: failure.message, detail: null };
  }
  return { headline: copy, detail: failure.message };
}
