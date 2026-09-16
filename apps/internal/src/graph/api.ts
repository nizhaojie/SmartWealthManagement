import { http } from "../api/http";
import type { CustomerGraphView } from "./types";

export function getCustomerGraph(
  customerId: number,
  opts: { expandFundManager?: boolean } = {},
): Promise<CustomerGraphView> {
  const query = opts.expandFundManager ? "?expand=fund_manager" : "";
  return http.get<CustomerGraphView>(`/api/internal/graph/customers/${customerId}${query}`);
}
