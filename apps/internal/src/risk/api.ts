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
  RiskRuleChange,
  RiskRuleCreateInput,
  RiskRuleSchema,
  RiskRuleUpdateInput,
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

export type RiskRuleListFilters = {
  /** 缺省即「全部」（未删除的已启用与已停用）。已删除与启停互斥。 */
  status?: "已启用" | "已停用" | "已删除";
  /** 判定字段的名录键。缺省即不限字段。 */
  field?: string;
};

export function listRiskRules(
  query: PageQuery,
  filters: RiskRuleListFilters = {},
): Promise<Paginated<RiskRule>> {
  // 状态与判定字段都是服务端参数：前端拿到当前页再过滤，会让「共 N 条」与实际行数
  // 对不上（ADR-0024）——总数与当前页必须由同一条查询派生。
  const search = queryString({
    page: query.page,
    page_size: query.page_size,
    status: filters.status,
    field: filters.field,
  });
  return http.get<Paginated<RiskRule>>(`/api/internal/risk-rules${search}`);
}

/**
 * 规则编辑器要的下拉项与允许组合。
 *
 * 选项一律来自这里，组件里不再留一份字段 / 算子清单：前端禁掉的选项与后端拒掉的组合
 * 一旦漂移，表现是「下拉里能选、一提交被拒」，而那张清单在后端注册表里。
 */
export function getRiskRuleSchema(): Promise<RiskRuleSchema> {
  return http.get<RiskRuleSchema>("/api/internal/risk-rules/schema");
}

/** 创建一条规则：编号由系统分配，校验（名录 / 搭配 / 值域）都由后端说了算。 */
export function createRiskRule(input: RiskRuleCreateInput): Promise<RiskRule> {
  return http.post<RiskRule>("/api/internal/risk-rules", input);
}

/**
 * 修改基本信息（名称 / 规则分类 / 描述 / 预警等级 / 规则权重）；判定形状、阈值与启停各有入口。
 */
export function updateRiskRule(ruleId: number, input: RiskRuleUpdateInput): Promise<RiskRule> {
  return http.patch<RiskRule>(`/api/internal/risk-rules/${ruleId}`, input);
}

/**
 * 软删一条规则。删除是终态，不提供恢复；理由是必填的，后端逐条再挡一次。
 *
 * 理由走请求体：`DELETE` 带体是刻意的，放进查询串会进访问日志。
 */
export function deleteRiskRule(ruleId: number, reason: string): Promise<RiskRule> {
  return http.delete<RiskRule>(`/api/internal/risk-rules/${ruleId}`, { reason });
}

/**
 * 一条规则的变更留痕，随时可读——包括已删除的规则：删除这件事本身也要可查。
 */
export function listRiskRuleChanges(ruleId: number): Promise<RiskRuleChange[]> {
  return http.get<RiskRuleChange[]>(`/api/internal/risk-rules/${ruleId}/changes`);
}

/**
 * 启停一条规则。
 *
 * 理由必填：五个写入口共用同一个留痕形状，有一个可以不署名，下一个人就会把它当漏写补上。
 * 代价是列表里的开关从「一下点开」变成「点一下先弹理由」。
 */
export function setRiskRuleEnabled(
  ruleId: number,
  enabled: boolean,
  reason: string,
): Promise<RiskRule> {
  return http.patch<RiskRule>(`/api/internal/risk-rules/${ruleId}/enabled`, { enabled, reason });
}

/** 阈值调整必须带理由：后端要求非空，且阈值形状要与算子匹配。 */
export function setRiskRuleThreshold(
  ruleId: number,
  threshold: Record<string, string>,
  reason: string,
): Promise<RiskRule> {
  return http.patch<RiskRule>(`/api/internal/risk-rules/${ruleId}/threshold`, { threshold, reason });
}

// 风控问答仍自持页面级会话标识，每次提问都带——它的会话语义与数据分析不同
// （后端只在数据分析那条链路上回落登录凭证里的 sid），所以这里要求标识必给。
type RiskQueryInput = AnalyticsQueryInput & { sessionId: string };

export function askRiskQuestion(
  input: RiskQueryInput,
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
