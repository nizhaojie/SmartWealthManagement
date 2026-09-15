import { http } from "../api/http";
import type { CustomerListItem, CustomerProfileView } from "./types";

export function listCustomers(): Promise<CustomerListItem[]> {
  return http.get<CustomerListItem[]>("/api/internal/customers");
}

export function getCustomerProfile(customerId: number): Promise<CustomerProfileView> {
  return http.get<CustomerProfileView>(`/api/internal/customers/${customerId}/profile`);
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
