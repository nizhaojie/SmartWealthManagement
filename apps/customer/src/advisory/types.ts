import type { ProductFilters } from "../products/types";

export type AdvisoryRequest = {
  id: number;
  request_no: string;
  customer_id: number;
  status: string;
  filters: ProductFilters;
  submitted_at: string;
};

export type AdvisoryRequestList = {
  requests: AdvisoryRequest[];
};
