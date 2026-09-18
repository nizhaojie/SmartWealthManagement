import { http } from "../api/http";
import type { CustomerAssets, CustomerProfileView, RiskAssessmentRecord } from "./types";

export function getCustomerProfile(customerId: number): Promise<CustomerProfileView> {
  return http.get<CustomerProfileView>(`/api/internal/customers/${customerId}/profile`);
}

export function getCustomerAssets(customerId: number): Promise<CustomerAssets> {
  return http.get<CustomerAssets>(`/api/internal/customers/${customerId}/assets`);
}

export function listRiskAssessments(customerId: number): Promise<RiskAssessmentRecord[]> {
  return http.get<RiskAssessmentRecord[]>(`/api/internal/customers/${customerId}/risk-assessments`);
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
