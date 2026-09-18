import { http } from "../api/http";

/**
 * 开户请求逐字段对齐 `OpenAccountRequest`。
 * 这一项是对 spec Q5「功能对等」的显式破例（Q9 批准）：现有前端从未暴露过这个接口。
 */
export type OpenAccountInput = {
  username: string;
  password: string;
  real_name: string;
  id_number: string;
  phone: string;
  customer_level: string;
  annual_income_range: string;
  total_assets: string;
  investment_experience: string;
  target_allocation?: Record<string, number> | null;
  product_preference?: Record<string, unknown> | null;
};

export type OpenedAccount = {
  id: number;
  username: string;
  real_name: string;
  customer_level: string;
  status: string;
  manager_id: number | null;
  opened_at: string;
};

export function openAccount(input: OpenAccountInput): Promise<OpenedAccount> {
  return http.post<OpenedAccount>("/api/internal/customers", input);
}
