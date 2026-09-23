import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type { ExternalOrderType, WorkOrder, WorkOrderDetail, WorkOrderStatus } from "./types";

export type WorkOrderFilters = {
  status?: WorkOrderStatus;
  alertId?: number;
  customerId?: number;
};

/**
 * 工单列表的一页。筛选与页码一起交给服务端（ADR-0024）：分页之后前端手里只有这一页，
 * 本地筛选只筛得动这一页，而「共 N 条」是**过滤后**的总数。
 */
export function listWorkOrders(
  filters: WorkOrderFilters = {},
  query: PageQuery,
): Promise<Paginated<WorkOrder>> {
  const search = queryString({
    status: filters.status,
    alert_id: filters.alertId,
    customer_id: filters.customerId,
    page: query.page,
    page_size: query.page_size,
  });
  return http.get<Paginated<WorkOrder>>(`/api/internal/work-orders${search}`);
}

export function getWorkOrder(workOrderId: number): Promise<WorkOrderDetail> {
  return http.get<WorkOrderDetail>(`/api/internal/work-orders/${workOrderId}`);
}

/** 外部建单：来源只支持客户投诉与转人工，理由是必填。 */
export function createExternalWorkOrder(input: {
  orderType: ExternalOrderType;
  customerId?: number | null;
  reason: string;
}): Promise<WorkOrder> {
  return http.post<WorkOrder>("/api/internal/work-orders", {
    order_type: input.orderType,
    customer_id: input.customerId ?? null,
    reason: input.reason,
  });
}

export function acceptWorkOrder(workOrderId: number, reason: string): Promise<WorkOrder> {
  return http.post<WorkOrder>(`/api/internal/work-orders/${workOrderId}/accept`, { reason });
}

export function completeWorkOrder(
  workOrderId: number,
  input: { reason: string; conclusion: string },
): Promise<WorkOrder> {
  return http.post<WorkOrder>(`/api/internal/work-orders/${workOrderId}/complete`, input);
}

export function closeWorkOrder(
  workOrderId: number,
  input: { reason: string; conclusion: string },
): Promise<WorkOrder> {
  return http.post<WorkOrder>(`/api/internal/work-orders/${workOrderId}/close`, input);
}
