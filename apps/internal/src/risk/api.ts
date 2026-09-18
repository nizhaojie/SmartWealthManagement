import { http } from "../api/http";
import { queryString } from "../api/query";
import type { AnalyticsQueryInput, AnalyticsQueryResponse } from "../analytics/types";
import type { WorkOrder } from "../work-orders/types";
import type {
  AlertDetail,
  AlertLevel,
  AlertStatus,
  AlertSummary,
  FocusType,
  RiskFocus,
  RiskRule,
} from "./types";

export type AlertFilters = {
  alertLevel?: AlertLevel;
  status?: AlertStatus;
  createdFrom?: string;
  createdTo?: string;
};

export function listAlerts(filters: AlertFilters = {}): Promise<AlertSummary[]> {
  return http.get<AlertSummary[]>(
    `/api/internal/risk-alerts${queryString({
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

export function listRiskFocus(focusType?: FocusType): Promise<RiskFocus[]> {
  return http.get<RiskFocus[]>(`/api/internal/risk-focus${queryString({ focus_type: focusType })}`);
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
