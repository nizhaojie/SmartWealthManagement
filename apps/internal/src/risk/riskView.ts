import { RISK_OFFICER, type EmployeeRole } from "../auth/identity";
import type { AlertLevel, AlertOrder, AlertSource, AlertStatus } from "./types";

/**
 * 排序下拉的选项：每一档就是接口认识的一个 `order_by`。
 *
 * 排序结果由服务端给出（ADR-0024），这里只提供「按哪一种排」的选择与它的说法——
 * 组件里不再留一份本地排序，两份排序必然在某一次翻页时对不上。
 */
export const ALERT_SORT_OPTIONS: { value: AlertOrder; label: string }[] = [
  { value: "created_desc", label: "按产生时间（最新在前）" },
  { value: "level_desc", label: "按等级（重到轻）" },
  { value: "confidence_desc", label: "按置信度（高到低）" },
  { value: "confidence_asc", label: "按置信度（低到高）" },
];

/**
 * 预警来源的呈现：内部补录用警示色。
 *
 * 这个区别不是装饰——客户发起的交易过了适当性与余额校验，内部补录的没有（它只对
 * 风控专员开放）。风控专员要在一眼扫过时就知道「这条能不能信」。
 */
export function alertSourceTagType(source: AlertSource): "info" | "warning" {
  return source === "内部补录" ? "warning" : "info";
}

/**
 * 来源的补充说明：只有内部补录需要解释，因为它是反直觉的那一种——一笔没经过适当性
 * 与余额校验的交易也进了监测。客户发起不必解释「客户发起的交易是客户发起的」。
 */
export function alertSourceNote(source: AlertSource): string | null {
  return source === "内部补录" ? "未经适当性与余额校验" : null;
}

/** 检查器里的模块筛选摘要由各页签写回来。 */
export type TabSummary = {
  headline: string;
  count: number | null;
};

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

/** 风控规则是风控专员的口径，启停与阈值调整都只放开给他。 */
export function canManageRiskRules(employeeRole: EmployeeRole | undefined): boolean {
  return employeeRole === RISK_OFFICER;
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

export function confidenceText(confidence: number): string {
  return confidence.toFixed(2);
}

/**
 * 风险关注记录的来源：事件载荷里是 Agent 的标识符，界面上要读得懂是谁提的醒。
 * 没登记过的来源原样显示——新接入一个 Agent 时，界面宁可丑一点，也不要假装
 * 它不存在。
 */
const FOCUS_SOURCE_LABELS: Record<string, string> = {
  "risk-monitoring-agent": "风控监测 Agent",
  "customer-service-agent": "智能客服 Agent",
};

export function focusSourceLabel(source: string): string {
  return FOCUS_SOURCE_LABELS[source] ?? source;
}
