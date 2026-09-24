import type { RoundFailure } from "./threadStore";

/** 受限查询的业务失败码（`backend/app/analytics/errors.py` 的那五个）。 */
export type AnalyticsFailureCode = 1101 | 1102 | 1103 | 1104 | 1105;

/**
 * 五种业务码各自的呈现文案。**不是一句「出错了」**：每一种没问成的原因不同，员工据此决定
 * 下一步怎么问（换范围 / 换说法 / 稍后再试），把五种压成一句话等于把这条线索丢了。
 *
 * 文案由码决定：界面说人话，后端那句话原样留着另起一行（见 `failureNotice`）。
 * 键是穷举的——少一种文案 TS 就报错，五种码不可能有哪一种悄悄落到一句笼统的提示上。
 */
const FAILURE_COPY: Record<AnalyticsFailureCode, string> = {
  1101: "超出可查范围：只能问语义视图覆盖的数据。",
  1102: "无法生成查询：这个问题没能翻译成一句可查的查询。",
  1103: "查询未通过安全校验：这一问没有执行。",
  1104: "查询超时：数据没有在时限内返回。",
  1105: "查询执行失败：查询没能跑完。",
};

function isFailureCode(code: number | null): code is AnalyticsFailureCode {
  return code !== null && code in FAILURE_COPY;
}

export type FailureNotice = {
  /** 由业务码决定的呈现文案；码认不出来时回落成后端写下的那句话。 */
  headline: string;
  /** 后端原文，另起一行留着诊断；已经当了呈现文案时为空。 */
  detail: string | null;
};

export function failureNotice(failure: RoundFailure): FailureNotice {
  if (!isFailureCode(failure.code)) {
    // 认不出的码不编文案：编一句我们并不知道原因的话，比后端原文更糟。
    return { headline: failure.message, detail: null };
  }
  return { headline: FAILURE_COPY[failure.code], detail: failure.message };
}
