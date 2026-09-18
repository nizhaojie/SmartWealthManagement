/**
 * 工单：处置某一事项的流程载体（CONTEXT「工单」）。
 * 生命周期 `待处理 → 处理中 → 已完成 | 已关闭`，每次流转都记处置人与非空理由。
 */
export const WORK_ORDER_STATUSES = ["待处理", "处理中", "已完成", "已关闭"] as const;
export type WorkOrderStatus = (typeof WORK_ORDER_STATUSES)[number];

/** 预警之外的两个来源：工单从来不是预警的附属物。 */
export const EXTERNAL_ORDER_TYPES = ["客户投诉", "转人工"] as const;
export type ExternalOrderType = (typeof EXTERNAL_ORDER_TYPES)[number];

export type WorkOrder = {
  id: number;
  work_order_no: string;
  order_type: string;
  sub_type: string | null;
  alert_id: number | null;
  customer_id: number | null;
  handler_id: number | null;
  handler_name: string;
  status: WorkOrderStatus;
  current_node: string;
  priority: string;
  biz_content: Record<string, unknown> | null;
  handle_reason: string | null;
  handle_result: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkOrderTransition = {
  from_status: WorkOrderStatus | null;
  to_status: WorkOrderStatus;
  handler_id: number;
  handler_name: string;
  reason: string;
  handled_at: string;
};

export type WorkOrderDetail = WorkOrder & { transitions: WorkOrderTransition[] };
