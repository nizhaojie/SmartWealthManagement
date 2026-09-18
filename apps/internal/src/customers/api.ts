import { http } from "../api/http";
import type { CustomerListItem } from "./types";

/**
 * 客户目录。画像、检查器、投顾、工单筛选与客户关系都用它——
 * 后端已按归属收窄，客户经理拿到的是自己名下的部分。
 */
export function listCustomers(): Promise<CustomerListItem[]> {
  return http.get<CustomerListItem[]>("/api/internal/customers");
}
