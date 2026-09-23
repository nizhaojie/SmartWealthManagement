// 客户画像左侧的客户目录：分页与关键字都归服务端（ADR-0024）。
//
// 这里跑的是真实的 API 层（只把 fetch 换掉），因此断言能直接落在「发出去的请求带了哪些
// 参数」上——这一条正是本页最要紧的地方：关键字若留在浏览器里过滤，只过滤得动当前页，
// 而「共 N 条」会变成「这一页里筛出了几条」，两个数字看起来都像是真的。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CustomerListItem } from "../customers/types";
import { apiError, requestedUrls, stubApiFetch, type ApiResponder } from "../testing";
import ProfileWorkspace from "./ProfileWorkspace.vue";

const PAGE_SIZE = 20;

function makeCustomer(id: number): CustomerListItem {
  return {
    id,
    username: `customer${String(id).padStart(2, "0")}`,
    real_name: `客户${String(id).padStart(2, "0")}`,
    customer_level: "普通",
    risk_level: "C3",
  };
}

const ALL_CUSTOMERS = Array.from({ length: 25 }, (_, index) => makeCustomer(index + 1));

/** 一个按关键字过滤、按页切片的最小服务端：口径与后端那一份一致（姓名或账号命中）。 */
function directoryResponder() {
  return (url: string) => {
    if (!url.includes("/api/internal/customers")) return undefined;
    const query = new URLSearchParams(url.split("?")[1] ?? "");
    const keyword = query.get("keyword") ?? "";
    const page = Number(query.get("page") ?? 1);
    const pageSize = Number(query.get("page_size") ?? PAGE_SIZE);
    const matched = ALL_CUSTOMERS.filter(
      (customer) =>
        customer.real_name.includes(keyword) || customer.username.includes(keyword),
    );
    const offset = (page - 1) * pageSize;
    return {
      items: matched.slice(offset, offset + pageSize),
      total: matched.length,
      page,
      page_size: pageSize,
    };
  };
}

let activeWrapper: VueWrapper | null = null;
let fetchMock: ReturnType<typeof stubApiFetch>;

async function mountWorkspace(respond: ApiResponder = directoryResponder()): Promise<VueWrapper> {
  fetchMock = stubApiFetch(respond);
  setActivePinia(createPinia());
  activeWrapper = mount(ProfileWorkspace, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return activeWrapper;
}

function customerUrls(): string[] {
  return requestedUrls(fetchMock, "/api/internal/customers");
}

function lastCustomerUrl(): string {
  return decodeURIComponent(customerUrls().at(-1) ?? "");
}

async function search(keyword: string): Promise<void> {
  await activeWrapper!.get('input[name="customer-keyword"]').setValue(keyword);
  await activeWrapper!.get('[data-testid="customer-search"]').trigger("submit");
  await flushPromises();
}

describe("客户画像的客户目录分页", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
    vi.unstubAllGlobals();
  });

  it("asks for the first page and shows how many there are in total", async () => {
    const page = await mountWorkspace();

    expect(customerUrls()).toHaveLength(1);
    expect(lastCustomerUrl()).toContain("page=1&page_size=20");
    expect(page.get('[data-testid="pagination-total"]').text()).toBe("共 25 条");
    expect(page.findAll(".list__item")).toHaveLength(PAGE_SIZE);
  });

  it("searches the whole directory on the server, not just the page in hand", async () => {
    // 「客户2」命中 客户20–25 共 6 位：第 1 页（客户01–20）里只有客户20 一位。
    // 本地过滤当前页只会留下那一位，且总数仍然是 25。
    const page = await mountWorkspace();

    await search("客户2");

    expect(lastCustomerUrl()).toContain("keyword=客户2&page=1");
    expect(page.get('[data-testid="pagination-total"]').text()).toBe("共 6 条");
    expect(page.findAll(".list__item")).toHaveLength(6);
    expect(page.text()).toContain("客户25");
  });

  it("turns the page and carries the keyword along", async () => {
    const page = await mountWorkspace();

    await search("客户");
    await page.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    // 少了关键字，第 2 页会变成「全部客户的第 2 页」，与搜索框里留着的字对不上。
    expect(lastCustomerUrl()).toContain("keyword=客户&page=2");
    expect(page.findAll(".list__item")).toHaveLength(5);
    expect(page.text()).toContain("客户25");
  });

  it("goes back to the first page when the keyword changes", async () => {
    const page = await mountWorkspace();

    await search("客户");
    await page.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(lastCustomerUrl()).toContain("page=2");

    await search("客户0");

    expect(lastCustomerUrl()).toContain("keyword=客户0&page=1");
  });

  it("says so when a keyword matches nobody", async () => {
    const page = await mountWorkspace();

    await search("查无此人");

    expect(page.get('[data-testid="customer-list-empty"]').text()).toContain("没有匹配的客户");
    expect(page.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("leaves a reason instead of a stale list when the directory fails to load", async () => {
    const page = await mountWorkspace(() =>
      apiError(500, "客户列表加载失败"),
    );

    expect(page.get('[data-testid="customer-list-error"]').text()).toContain("客户列表加载失败");
    expect(page.findAll(".list__item")).toHaveLength(0);
    // `total` 归零，分页条与列表同进同退：留着它，人就困在取不到的那一页上。
    expect(page.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });
});
