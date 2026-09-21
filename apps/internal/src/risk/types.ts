import type { WorkOrder, WorkOrderStatus } from "../work-orders/types";

export const ALERT_LEVELS = ["轻度", "中度", "重度"] as const;
export type AlertLevel = (typeof ALERT_LEVELS)[number];

// 预警自身的处置状态只有这三个：未处理，以及由人做出的两个结论。没有「自动关闭」
// 这一档——系统不会因为置信度低或超时把预警消化掉。
export const ALERT_STATUSES = ["未处理", "已排除", "已升级"] as const;
export type AlertStatus = (typeof ALERT_STATUSES)[number];

/**
 * 一条命中规则及其依据快照。
 *
 * `field_label` / `observed_value` / `operator_symbol` / `threshold` 是风控专员判断
 * 误报时要看的东西——「交易金额 520000 ≥ 阈值 50000」。依据在命中那一刻固化，
 * 规则阈值后来被调过也不会改写它。
 */
export type AlertRuleHit = {
  rule_code: string;
  rule_name: string;
  category: string;
  alert_level: AlertLevel;
  weight: number;
  field: string;
  field_label: string;
  operator: string;
  operator_label: string;
  operator_symbol: string;
  threshold: string;
  observed_value: string;
  evidence: string;
};

/**
 * 预警的来源：**客户发起 / 内部补录**，依据是关联交易有没有经办员工（Q22）。
 *
 * 它决定这条预警值不值得信：客户发起的交易过了适当性与余额校验，内部补录的没有
 * ——那是一条只对风控专员开放的口子。
 */
export const ALERT_SOURCES = ["客户发起", "内部补录"] as const;
export type AlertSource = (typeof ALERT_SOURCES)[number];

export type AlertSummary = {
  id: number;
  customer_id: number;
  customer_name: string;
  alert_type: string;
  alert_level: AlertLevel;
  confidence: number;
  rule_codes: string[];
  rule_count: number;
  transaction_ids: number[];
  status: AlertStatus;
  source: AlertSource;
  created_at: string;
  work_order_id: number | null;
  work_order_status: WorkOrderStatus | null;
};

export type AlertTransaction = {
  id: number;
  transaction_no: string;
  customer_id: number;
  product_id: number;
  product_code: string;
  product_name: string;
  transaction_type: string;
  amount: string;
  shares: string;
  nav: string;
  fee: string;
  status: string;
  occurred_at: string;
};

export type AlertCustomer = {
  customer_id: number;
  real_name: string;
  customer_level: string;
  risk_level: string | null;
  manager_name: string;
};

export type AlertHistoryEntry = {
  id: number;
  alert_type: string;
  alert_level: AlertLevel;
  confidence: number;
  rule_codes: string[];
  status: AlertStatus;
  created_at: string;
};

export type AlertDetail = {
  id: number;
  customer_id: number;
  customer_name: string;
  alert_type: string;
  alert_level: AlertLevel;
  confidence: number;
  rule_codes: string[];
  rule_hits: AlertRuleHit[];
  transaction_ids: number[];
  trigger_detail: string;
  status: AlertStatus;
  source: AlertSource;
  handler_id: number | null;
  handle_result: string | null;
  handled_by_name: string;
  created_at: string;
  customer: AlertCustomer;
  transactions: AlertTransaction[];
  customer_history: AlertHistoryEntry[];
  work_order: WorkOrder | null;
};

// 风险关注：其他 Agent 提醒过来的东西（CONTEXT「风险关注」）。它不是预警（规则
// 命中的事实记录），也不是工单（处置流程的载体），而是「谁在什么时候因为什么提醒了
// 谁」的留痕；要处置就另开工单，不在这一行上流转。
export const FOCUS_TYPES = ["风控预警", "高风险意图"] as const;
export type FocusType = (typeof FOCUS_TYPES)[number];

export type RiskFocus = {
  id: number;
  customer_id: number;
  customer_name: string;
  focus_type: FocusType;
  severity: AlertLevel | null;
  reason: string;
  source: string;
  trace_id: string | null;
  occurred_at: string;
};

export type RiskRule = {
  id: number;
  rule_code: string;
  rule_name: string;
  category: string;
  description: string;
  field: string;
  field_label: string;
  operator: string;
  operator_label: string;
  threshold: Record<string, string>;
  threshold_text: string;
  window_hours: number | null;
  alert_level: AlertLevel;
  weight: number;
  enabled: boolean;
};
