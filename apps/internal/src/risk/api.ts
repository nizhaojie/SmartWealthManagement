import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type { AnalyticsQueryInput, AnalyticsQueryResponse } from "../analytics/types";
import type { WorkOrder } from "../work-orders/types";
import type {
  AlertDetail,
  AlertLevel,
  AlertOrder,
  AlertStatus,
  AlertSummary,
  FocusType,
  RiskFocus,
  RiskRule,
} from "./types";

/**
 * 预警列表的查询条件：筛选与排序都在这里。
 *
 * 排序方式也是查询条件之一（`order_by`），排序由服务端执行（ADR-0024）——分页之后
 * 本地排序只排得动当前页。
 */
export type AlertFilters = {
  alertLevel?: AlertLevel;
  status?: AlertStatus;
  customerId?: number;
  createdFrom?: string;
  createdTo?: string;
  orderBy?: AlertOrder;
};

export function listAlerts(
  filters: AlertFilters = {},
  query: PageQuery,
): Promise<Paginated<AlertSummary>> {
  const search = queryString({
    alert_level: filters.alertLevel,
    status: filters.status,
    customer_id: filters.customerId,
    created_from: filters.createdFrom,
    created_to: filters.createdTo,
    order_by: filters.orderBy,
    page: query.page,
    page_size: query.page_size,
  });
  return http.get<Paginated<AlertSummary>>(`/api/internal/risk-alerts${search}`);
}

export function getAlert(alertId: number): Promise<AlertDetail> {
  return http.get<AlertDetail>(`/api/internal/risk-alerts/${alertId}`);
}

/** 三个处置动作共用同一个「理由必填」的约定，后端逐条再挡一次。 */
export function excludeAlert(alertId: number, reason: string): Promise<AlertDetail> {
  return http.post<AlertDetail>(`/api/internal/risk-alerts/${alertId}/exclude`, { reason });
}

export function escalateAlert(alertId: number, reason: string): Promise<AlertDetail> {
  return http.post<AlertDetail>(`/api/internal/risk-alerts/${alertId}/escalate`, { reason });
}

export function deriveWorkOrder(alertId: number, reason: string): Promise<WorkOrder> {
  return http.post<WorkOrder>(`/api/internal/risk-alerts/${alertId}/work-orders`, { reason });
}

export function listRiskFocus(
  filters: { focusType?: FocusType } = {},
  query: PageQuery,
): Promise<Paginated<RiskFocus>> {
  const search = queryString({
    focus_type: filters.focusType,
    page: query.page,
    page_size: query.page_size,
  });
  return http.get<Paginated<RiskFocus>>(`/api/internal/risk-focus${search}`);
}

export function listRiskRules(query: PageQuery): Promise<Paginated<RiskRule>> {
  const search = queryString({ page: query.page, page_size: query.page_size });
  return http.get<Paginated<RiskRule>>(`/api/internal/risk-rules${search}`);
}

export function setRiskRuleEnabled(ruleId: number, enabled: boolean): Promise<RiskRule> {
  return http.patch<RiskRule>(`/api/internal/risk-rules/${ruleId}/enabled`, {
    enabled,
    // 启停不强制理由（阈值调整才强制）：这里没有要解释的口径变化，只记谁改的。
    reason: "",
  });
}

/** 阈值调整必须带理由：后端要求非空，且阈值形状要与算子匹配。 */
export function setRiskRuleThreshold(
  ruleId: number,
  threshold: Record<string, string>,
  reason: string,
): Promise<RiskRule> {
  return http.patch<RiskRule>(`/api/internal/risk-rules/${ruleId}/threshold`, { threshold, reason });
}

export function askRiskQuestion(
  input: AnalyticsQueryInput,
): Promise<AnalyticsQueryResponse> {
  // 走风控监测 Agent 自己的查询入口：视图范围收窄到风控域，与数据分析
  // 模块互不影响（同一条受限查询链路，不同的 Agent 配置）。
  return http.post<AnalyticsQueryResponse>("/api/internal/risk-monitoring/query", {
    question: input.question,
    session_id: input.sessionId,
  });
}

export function listRiskQueryExamples(): Promise<{ question: string }[]> {
  return http.get<{ question: string }[]>("/api/internal/risk-monitoring/examples");
}
