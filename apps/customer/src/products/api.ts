import { http } from "../api/http";
import type { Product, ProductFilters, ProductList } from "./types";

function queryString(filters: ProductFilters): string {
  const params = new URLSearchParams();
  if (filters.product_type) params.set("product_type", filters.product_type);
  if (filters.risk_level) params.set("risk_level", filters.risk_level);
  if (filters.min_amount) params.set("min_amount", filters.min_amount);
  if (filters.min_expected_return) params.set("min_expected_return", filters.min_expected_return);
  if (filters.max_term_days) params.set("max_term_days", filters.max_term_days);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function listProducts(filters: ProductFilters = {}): Promise<ProductList> {
  return http.get<ProductList>(`/api/customer/products${queryString(filters)}`);
}

export function getProduct(productCode: string): Promise<Product> {
  return http.get<Product>(`/api/customer/products/${encodeURIComponent(productCode)}`);
}
