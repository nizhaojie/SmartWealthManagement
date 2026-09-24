import type { WorkOrder, WorkOrderStatus } from "../work-orders/types";

export const ALERT_LEVELS = ["轻度", "中度", "重度"] as const;
export type AlertLevel = (typeof ALERT_LEVELS)[number];

/**
 * 预警列表的排序方式，取值就是列表接口的 `order_by` 参数（ADR-0024）。
 *
 * 排序**在服务端做**：分页之后前端手里只有当前页，本地排序会让「按等级」只在这一页
 * 内成立，翻页即乱。`level_desc` 是重到轻，同级内按时间倒序。
 */
export type AlertOrder = "created_desc" | "confidence_desc" | "confidence_asc" | "level_desc";

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
  /**
   * 软删标记（ADR-0027）：有值表示这条规则已被删除，行还在库里、留痕还指着它。
   *
   * 状态选「已删除」才见得到这样的行，界面上置灰只读——能删就能删错，只是没有恢复
   * 入口：可逆的「让它不生效」由 `enabled` 承担。
   */
  deleted_at: string | null;
};

// ---------------- 规则编辑器要的下拉项（GET /schema） ----------------
//
// 这一组类型是「前端能配出什么」的**契约副本**：真正的清单在后端的注册表里，前端只
// 照着渲染。两张清单互抄时漂移的表现是「下拉里能选、一提交被拒」——不会有断言失败，
// 只会有人反复试，所以选项一律来自这一份载荷，不在组件里硬编码。

/** 阈值的物理值域：这个字段的阈值允许落在哪，`text` 可以直接展示。 */
export type RuleValueRange = {
  min: string | null;
  max: string | null;
  min_inclusive: boolean;
  max_inclusive: boolean;
  text: string;
};

/** 一个可判定字段：标签、说明、允许的算子（字段 × 算子矩阵的那一行）与阈值值域。 */
export type RuleFieldSpec = {
  key: string;
  label: string;
  description: string;
  allowed_operators: string[];
  value_range: RuleValueRange | null;
};

/**
 * 算子的作用域：单笔 / 时间窗 / 自然日。它是「要不要填窗长」的唯一依据——时间窗算子
 * 必须有 `window_hours`，其余算子提交时置 NULL。
 */
export type RuleOperatorScope = "single" | "window" | "daily";

/** 一个算子：标签、符号与它自己的阈值键（`gte` 一个、`between` 两个）。 */
export type RuleOperatorSpec = {
  key: string;
  label: string;
  symbol: string;
  scope: RuleOperatorScope;
  threshold_keys: string[];
};

export type RiskRuleSchema = {
  categories: string[];
  fields: RuleFieldSpec[];
  operators: RuleOperatorSpec[];
};

/** 五个留痕类型（`fin_risk_rule_change.change_type`）：三个写入口各记自己那一条。 */
export const RULE_CHANGE_TYPES = ["规则新建", "规则修改", "规则删除", "阈值调整", "启停变更"] as const;
export type RiskRuleChangeType = (typeof RULE_CHANGE_TYPES)[number];

/**
 * 一条规则变更留痕。
 *
 * `old_value` / `new_value` 装的是**整份快照**（新建与删除是「无 → 有」「有 → 无」的
 * 一对镜像），所以一条记录单独就能回答「当时是什么样」，不必再去读那行。
 */
export type RiskRuleChange = {
  id: number;
  rule_code: string;
  change_type: RiskRuleChangeType;
  old_value: Record<string, unknown>;
  new_value: Record<string, unknown>;
  changed_by: number;
  changed_by_name: string;
  reason: string;
  changed_at: string;
};

/** 创建一条规则的请求体：全部可填参数 + 必填理由，编号由系统分配。 */
export type RiskRuleCreateInput = {
  rule_name: string;
  category: string;
  description: string;
  field: string;
  operator: string;
  threshold: Record<string, string>;
  window_hours: number | null;
  alert_level: AlertLevel;
  /** 规则权重：空值表示「用默认的 1.00」；界面上的区间由数字框与后端各挡一次。 */
  weight: number | null;
  enabled: boolean;
  reason: string;
};

/**
 * 修改一条规则的基本信息：名称 / 规则分类 / 描述 / 预警等级 / 规则权重 + 必填理由。
 *
 * 判定形状、阈值与启停**不在这份请求体里**：带了任一个后端一律 400（ADR-0026）——
 * 改判定形状就是换了一条规则，阈值与启停各有专门入口、各自单独留痕。
 */
export type RiskRuleUpdateInput = {
  rule_name: string;
  category: string;
  description: string;
  alert_level: AlertLevel;
  weight: number | null;
  reason: string;
};
