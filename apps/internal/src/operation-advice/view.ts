import type { ReviewStatus } from "./types";

/**
 * 进度的呈现分两列，**不合成一个字段**：审核进度说「顾问看了没有」，客户决定说
 * 「客户答了没有」。合成一处就会丢掉其中一半，而丢掉的那一半正是客户经理此刻要的
 * 答案——未放行时「客户决定」是空而不是「待客户决定」，客户此刻根本读不到这条建议。
 */

export function reviewStatusTagType(
  status: ReviewStatus,
): "success" | "danger" | "warning" | "info" {
  if (status === "已放行") return "success";
  if (status === "已驳回") return "danger";
  if (status === "处理中") return "warning";
  return "info";
}

/** 客户决定是终态：接受与拒绝各自有颜色，「待客户决定」是等待、用中性色。 */
export function customerStatusTagType(
  status: string,
): "success" | "danger" | "warning" | "info" {
  if (status === "已接受") return "success";
  if (status === "已拒绝") return "danger";
  if (status === "待客户决定") return "warning";
  return "info";
}
