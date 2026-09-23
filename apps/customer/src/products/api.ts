import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type { CandidatePool, Product, ProductFilters } from "./types";

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

/** 可购范围内的一页产品，恒按产品代码升序（ADR-0005），筛选条件随页码一并传给服务端。 */
export function listProducts(
  query: PageQuery,
  filters: ProductFilters = {},
): Promise<Paginated<Product>> {
  const search = queryString({
    ...compactFilters(filters),
    page: query.page,
    page_size: query.page_size,
  });
  return http.get<Paginated<Product>>(`/api/customer/products${search}`);
}

/** 后端页长上限（`app/pagination.py` 的 `MAX_PAGE_SIZE`）。 */
const ALL_PAGE_SIZE = 100;

/**
 * 全量在售产品：交易页的申购/赎回下拉要的是**全部**产品，不是某一页。
 *
 * 下拉选项不是分页对象（spec 的范围排除项），但它与产品筛选共用同一个已分页的接口：
 * 只取第一页的话，第 101 只产品会从下拉里消失，而界面上没有任何一处会显示少了产品。
 */
export async function listAllProducts(): Promise<Product[]> {
  const products: Product[] = [];
  let page = 1;
  for (;;) {
    const result = await listProducts({ page, page_size: ALL_PAGE_SIZE });
    products.push(...result.items);
    if (!result.items.length || products.length >= result.total) {
      return products;
    }
    page += 1;
  }
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
