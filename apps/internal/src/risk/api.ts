import { http } from "../api/http";
import type {
  AlertDetail,
  AlertLevel,
  AlertStatus,
  AlertSummary,
  RiskRule,
  WorkOrder,
  WorkOrderDetail,
  WorkOrderStatus,
} from "./types";

export type AlertFilters = {
  alertLevel?: AlertLevel;
  status?: AlertStatus;
  createdFrom?: string;
  createdTo?: string;
};

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const result = search.toString();
  return result ? `?${result}` : "";
}

export function listAlerts(filters: AlertFilters = {}): Promise<AlertSummary[]> {
  return http.get<AlertSummary[]>(
    `/api/internal/risk-alerts${query({
      alert_level: filters.alertLevel,
      status: filters.status,
      created_from: filters.createdFrom,
      created_to: filters.createdTo,
    })}`,
  );
}

export function getAlert(alertId: number): Promise<AlertDetail> {
  return http.get<AlertDetail>(`/api/internal/risk-alerts/${alertId}`);
}

export function excludeAlert(alertId: number, reason: string): Promise<AlertDetail> {
  return http.post<AlertDetail>(`/api/internal/risk-alerts/${alertId}/exclude`, { reason });
}

export function escalateAlert(alertId: number, reason: string): Promise<AlertDetail> {
  return http.post<AlertDetail>(`/api/internal/risk-alerts/${alertId}/escalate`, { reason });
}

export function deriveWorkOrder(alertId: number, reason: string): Promise<WorkOrder> {
  return http.post<WorkOrder>(`/api/internal/risk-alerts/${alertId}/work-orders`, { reason });
}

export function listWorkOrders(filters: { status?: WorkOrderStatus } = {}): Promise<WorkOrder[]> {
  return http.get<WorkOrder[]>(`/api/internal/work-orders${query({ status: filters.status })}`);
}

export function getWorkOrder(workOrderId: number): Promise<WorkOrderDetail> {
  return http.get<WorkOrderDetail>(`/api/internal/work-orders/${workOrderId}`);
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

export function listRiskRules(): Promise<RiskRule[]> {
  return http.get<RiskRule[]>("/api/internal/risk-rules");
}

export function setRiskRuleEnabled(ruleId: number, enabled: boolean): Promise<RiskRule> {
  return http.patch<RiskRule>(`/api/internal/risk-rules/${ruleId}/enabled`, {
    enabled,
    // 启停不强制理由（阈值调整才强制）：这里没有要解释的口径变化，只记谁改的。
    reason: "",
  });
}
