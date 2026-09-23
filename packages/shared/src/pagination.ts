/**
 * 分页契约的前端一侧（ADR-0024）：列表接口的 `data` 恒为 `{items, total, page, page_size}`。
 *
 * 这份类型与那个 composable 是两端共用的：`page` 从 1 起、`page_size` 默认 20，
 * 都是后端 `app/pagination.py` 的同名口径。前端的页码与后端的页码一旦各有一套默认值，
 * 表现就是「第一页少了 20 条」这种没人会去查的错位。
 */
import { ref, shallowRef, type Ref } from "vue";
import { ApiError } from "./http";

export const DEFAULT_PAGE_SIZE = 20;

/** 列表接口 `data` 的统一形状。 */
export type Paginated<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

/** 请求一页时带上的那对参数：与后端 query 同名，直接铺进查询串。 */
export type PageQuery = {
  page: number;
  page_size: number;
};

export type PaginatedLoader<T> = (query: PageQuery) => Promise<Paginated<T>>;

export type UsePaginationOptions = {
  /** 每页条数，默认 `DEFAULT_PAGE_SIZE`；筛选项里若给了页长，让它一并生效。 */
  pageSize?: number;
  /** 取不到时给调用方的一句话原因（服务端给了 `ApiError.message` 就用它的）。 */
  failureMessage?: string;
};

export type Pagination<T> = {
  /** 当前页的条目。取不到时为空，不留上一页——那会让上一页冒充当页。 */
  items: Ref<T[]>;
  total: Ref<number>;
  page: Ref<number>;
  pageSize: Ref<number>;
  loading: Ref<boolean>;
  errorMessage: Ref<string>;
  /** 用当前页码取一页（首次进入、或取失败后重试）。 */
  refresh: () => Promise<void>;
  /** 翻到某一页并取回来。页码不变时不动——el-pagination 会重复发同一页。 */
  goTo: (page: number) => Promise<void>;
  /** 筛选条件变了：回到第一页再取。停在第 3 页会看到「筛选后为空」，那不是筛选的结果。 */
  reset: () => Promise<void>;
};

/**
 * 一页列表的取数与页码状态。
 *
 * 它只做三件事：拿着 `page`/`page_size` 去调调用方给的取数函数、把返回的 `items` 与
 * `total` 落地、失败时清空并留一句原因。页面因此不必各写一遍「载入中／失败／空」的三态。
 *
 * `load` 是以闭包形式传进来的，所以筛选条件（reactive 对象）在每次调用时重新读取——
 * 改完筛选调 `reset()`，取到的就是新条件的第一页。
 */
export function usePagination<T>(
  load: PaginatedLoader<T>,
  options: UsePaginationOptions = {},
): Pagination<T> {
  const items = shallowRef<T[]>([]);
  const total = ref(0);
  const page = ref(1);
  const pageSize = ref(options.pageSize ?? DEFAULT_PAGE_SIZE);
  const loading = ref(false);
  const errorMessage = ref("");

  async function refresh(): Promise<void> {
    loading.value = true;
    errorMessage.value = "";
    try {
      const result = await load({ page: page.value, page_size: pageSize.value });
      items.value = result.items;
      total.value = result.total;
      // 窗口以**服务端回传的**为准（ADR-0024）：页长超上限会在后端被钳到 100，
      // 前端若还按 200 算总页数，翻页就会重读或漏读——两边各自的数字都「对」，
      // 错只错在它们不是同一个数。
      page.value = result.page;
      pageSize.value = result.page_size;
    } catch (caught) {
      // 取不到就是取不到：条目清空、总数归零。留着一份旧数据，页面会在「加载失败」
      // 下面继续显示上一次的记录，而那个总数还会驱动翻页控件——两处都在陈述没发生过的事。
      items.value = [];
      total.value = 0;
      errorMessage.value =
        caught instanceof ApiError ? caught.message : (options.failureMessage ?? "列表加载失败");
    } finally {
      loading.value = false;
    }
  }

  async function goTo(next: number): Promise<void> {
    if (next === page.value) {
      return;
    }
    page.value = next;
    await refresh();
  }

  async function reset(): Promise<void> {
    page.value = 1;
    await refresh();
  }

  return { items, total, page, pageSize, loading, errorMessage, refresh, goTo, reset };
}
