import type { PageQuery, Paginated } from "@wealth/shared";
import { http } from "../api/http";
import { queryString } from "../api/query";
import type { CustomerListItem } from "./types";

/**
 * 目录的筛选条件。关键字由**服务端**过滤（ADR-0024）：目录分页之后前端手里只有一页，
 * 在浏览器里过滤只过滤得动这一页——「共 N 条」会变成「这一页里筛出了几条」。
 */
export type CustomerFilters = {
  keyword?: string;
};

/**
 * 客户目录的一页。画像、检查器、投顾、工单筛选与客户关系都用它——
 * 后端已按归属收窄，客户经理拿到的是自己名下的部分。
 */
export function listCustomers(
  query: PageQuery,
  filters: CustomerFilters = {},
): Promise<Paginated<CustomerListItem>> {
  const search = queryString({
    keyword: filters.keyword,
    page: query.page,
    page_size: query.page_size,
  });
  return http.get<Paginated<CustomerListItem>>(`/api/internal/customers${search}`);
}

/** 后端页长上限（`app/pagination.py` 的 `MAX_PAGE_SIZE`）。 */
const ALL_PAGE_SIZE = 100;

/**
 * 完整客户目录：下拉与筛选项要的是**全部**客户，不是某一页。
 *
 * 目录按页给（ADR-0024），这里把页翻完再拼。下拉与筛选不是分页对象（spec 的范围排除
 * 项），但它们与目录共用同一个接口：只取第一页的话，第 101 位客户会从选中框里消失，
 * 而界面上没有任何一处会显示少了人。
 */
export async function listAllCustomers(): Promise<CustomerListItem[]> {
  const customers: CustomerListItem[] = [];
  let page = 1;
  for (;;) {
    const result = await listCustomers({ page, page_size: ALL_PAGE_SIZE });
    customers.push(...result.items);
    if (!result.items.length || customers.length >= result.total) {
      return customers;
    }
    page += 1;
  }
}
