import { http } from "../api/http";
import { queryString } from "../api/query";
import type { ExternalOrderType, WorkOrder, WorkOrderDetail, WorkOrderStatus } from "./types";

export type WorkOrderFilters = {
  status?: WorkOrderStatus;
  alertId?: number;
  customerId?: number;
};

export function listWorkOrders(filters: WorkOrderFilters = {}): Promise<WorkOrder[]> {
  return http.get<WorkOrder[]>(
    `/api/internal/work-orders${queryString({
      status: filters.status,
      alert_id: filters.alertId,
      customer_id: filters.customerId,
    })}`,
  );
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
