import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type { CustomerAssets, CustomerProfileView, RiskAssessmentRecord } from "./types";

export function getCustomerProfile(customerId: number): Promise<CustomerProfileView> {
  return http.get<CustomerProfileView>(`/api/internal/customers/${customerId}/profile`);
}

export function getCustomerAssets(customerId: number): Promise<CustomerAssets> {
  return http.get<CustomerAssets>(`/api/internal/customers/${customerId}/assets`);
}

/**
 * 某位客户的历次风险评测，最近的一次在最前（ADR-0024）。
 *
 * 与画像分开取：画像是「现在是什么样」，评测历史是一条独立列表——它随页数增长，
 * 不该被塞进画像里一次性给完。
 */
export function listRiskAssessments(
  customerId: number,
  query: PageQuery,
): Promise<Paginated<RiskAssessmentRecord>> {
  const search = queryString({ page: query.page, page_size: query.page_size });
  return http.get<Paginated<RiskAssessmentRecord>>(
    `/api/internal/customers/${customerId}/risk-assessments${search}`,
  );
}

/**
 * 手工修正标签。`source` 传「理财顾问手工修正」时后端要求当前员工是理财顾问，
 * 且 `reason` 非空——理由不是可选项，它是「谁凭什么改了画像」的留痕。
 */
export function writeProfileTag(input: {
  customerId: number;
  tagKey: string;
  value: unknown;
  source: string;
  reason?: string;
}): Promise<CustomerProfileView> {
  return http.put<CustomerProfileView>(`/api/internal/customers/${input.customerId}/profile/tags`, {
    tag_key: input.tagKey,
    value: input.value,
    source: input.source,
    reason: input.reason,
  });
}
