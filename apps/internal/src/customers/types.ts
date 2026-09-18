/** 客户目录里的一行：`GET /api/internal/customers` 的返回形状（已按归属收窄）。 */
export type CustomerListItem = {
  id: number;
  username: string;
  real_name: string;
  customer_level: string;
  risk_level: string | null;
};
