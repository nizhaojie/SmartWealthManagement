import { http } from "../api/http";
import type { ProductFilters } from "../products/types";
import type { AdvisoryRequest, AdvisoryRequestList } from "./types";

export function submitAdvisoryRequest(filters: ProductFilters): Promise<AdvisoryRequest> {
  return http.post<AdvisoryRequest>("/api/customer/advisory-requests", filters);
}

export function listAdvisoryRequests(): Promise<AdvisoryRequestList> {
  return http.get<AdvisoryRequestList>("/api/customer/advisory-requests");
}
