import { ApiError } from "@wealth/shared";
import { RISK_OFFICER, type EmployeeRole } from "../auth/identity";
import type { AlertLevel, AlertStatus, AlertSummary, WorkOrderStatus } from "./types";

export type AlertSort = "created_desc" | "confidence_desc" | "confidence_asc";

export const ALERT_SORT_OPTIONS: { value: AlertSort; label: string }[] = [
  { value: "created_desc", label: "按产生时间（最新在前）" },
  { value: "confidence_desc", label: "按置信度（高到低）" },
  { value: "confidence_asc", label: "按置信度（低到高）" },
];

export function levelTagType(level: AlertLevel): "danger" | "warning" | "info" {
  if (level === "重度") return "danger";
  if (level === "中度") return "warning";
  return "info";
}

export function statusTagType(status: AlertStatus): "warning" | "success" | "info" {
  if (status === "已排除") return "info";
  if (status === "已升级") return "success";
  return "warning";
}

export function workOrderTagType(
  status: WorkOrderStatus,
): "warning" | "primary" | "success" | "info" {
  if (status === "处理中") return "primary";
  if (status === "已完成") return "success";
  if (status === "已关闭") return "info";
  return "warning";
}

/**
 * 排序只发生在拿回来的这一批上：筛选在服务端做，服务端返回的已经是「最新的在最
 * 前面」，而置信度是同一批数据的另一种排列，不必再往返一次。
 */
export function sortAlerts(alerts: AlertSummary[], sortBy: AlertSort): AlertSummary[] {
  if (sortBy === "created_desc") {
    return alerts;
  }
  const direction = sortBy === "confidence_desc" ? -1 : 1;
  return [...alerts].sort((left, right) => {
    if (left.confidence !== right.confidence) {
      return direction * (left.confidence - right.confidence);
    }
    // 并列时新的在前：排序要稳定，也不能让两条同分预警的顺序随机漂。
    return right.id - left.id;
  });
}

/** 只有风控专员能处置，且只能处置还没被判定过的预警。 */
export function canDispose(employeeRole: EmployeeRole | undefined, status: AlertStatus): boolean {
  return employeeRole === RISK_OFFICER && status === "未处理";
}

/** 一条预警最多派生一张工单，所以已经有工单时不再给派生入口。 */
export function canDeriveWorkOrder(
  employeeRole: EmployeeRole | undefined,
  alert: { status: AlertStatus; work_order_id: number | null },
): boolean {
  return canDispose(employeeRole, alert.status) && alert.work_order_id === null;
}

/**
 * 工单能流转的两个状态，以及唯一能流转它的角色。
 *
 * 终态（已完成 / 已关闭）没有下一步——这与后端 `NEXT_STATUSES` 是同一张表，
 * 界面据此把处置表单换成一句说明，而不是让按钮点下去才报 409。
 */
export function canHandleWorkOrder(
  employeeRole: EmployeeRole | undefined,
  status: WorkOrderStatus,
): boolean {
  return employeeRole === RISK_OFFICER && (status === "待处理" || status === "处理中");
}

export function confidenceText(confidence: number): string {
  return confidence.toFixed(2);
}

/**
 * 后端给的是它自己写下的那句话，直接透传；只有拿不到消息时（网络断了）才用兜底
 * 文案——用一句写死的话盖过后端的具体原因，等于把可诊断的信息丢掉。
 */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : fallback;
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}
