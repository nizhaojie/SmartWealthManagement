import { http } from "../api/http";
import type {
  CustomerAssets,
  CustomerListItem,
  CustomerProfileView,
  RiskAssessmentRecord,
} from "./types";

export function listCustomers(): Promise<CustomerListItem[]> {
  return http.get<CustomerListItem[]>("/api/internal/customers");
}

export function getCustomerProfile(customerId: number): Promise<CustomerProfileView> {
  return http.get<CustomerProfileView>(`/api/internal/customers/${customerId}/profile`);
}

export function getCustomerAssets(customerId: number): Promise<CustomerAssets> {
  return http.get<CustomerAssets>(`/api/internal/customers/${customerId}/assets`);
}

export function listRiskAssessments(customerId: number): Promise<RiskAssessmentRecord[]> {
  return http.get<RiskAssessmentRecord[]>(`/api/internal/customers/${customerId}/risk-assessments`);
}

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
