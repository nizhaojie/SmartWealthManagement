import { http } from "../api/http";
import type { CandidatePool, Product, ProductFilters, ProductList } from "./types";

/**
 * 去掉空条件：「填了才算数」这条约定只写一处——查询串与方案请求体共用它，
 * 免得 GET 少传一个空参数、POST 却把空串当条件提交上去。
 */
export function compactFilters(filters: ProductFilters): Record<string, string> {
  const filled: Record<string, string> = {};
  if (filters.product_type) filled.product_type = filters.product_type;
  if (filters.risk_level) filled.risk_level = filters.risk_level;
  if (filters.min_amount) filled.min_amount = filters.min_amount;
  if (filters.min_expected_return) filled.min_expected_return = filters.min_expected_return;
  if (filters.max_term_days) filled.max_term_days = filters.max_term_days;
  return filled;
}

function queryString(filters: ProductFilters): string {
  const query = new URLSearchParams(compactFilters(filters)).toString();
  return query ? `?${query}` : "";
}

export function listProducts(filters: ProductFilters = {}): Promise<ProductList> {
  return http.get<ProductList>(`/api/customer/products${queryString(filters)}`);
}

export function getProduct(productCode: string): Promise<Product> {
  return http.get<Product>(`/api/customer/products/${encodeURIComponent(productCode)}`);
}

/**
 * 适当性硬过滤后的候选池。客户侧只读它给出的「可购范围」用于说明，
 * 不据此做任何排序或适配性表述。
 *
 * 注意：这个接口在服务端会顺带落一条适当性判定记录，因此每次进入产品筛选页都会留痕。
 * 可购范围没有第二个来源（前端自行由 Cn 推 Rn 就是把适当性交给界面裁量），
 * 这个副作用是本 slice 明确接受的代价。
 */
export function getCandidatePool(): Promise<CandidatePool> {
  return http.get<CandidatePool>("/api/customer/candidate-pool");
}
