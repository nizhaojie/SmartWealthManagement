// 客户关系的名下客户列表：表格翻页（ADR-0024），以及同页上「操作建议」选中框的口径。
//
// 后者是本页唯一的分叉：表格要的是**这一页**，选中框要的是**全部**客户。两者共用一个
// 接口，所以这里分别断「表格按 20 条一页取」与「目录被翻完再给选中框」。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { CustomerListItem } from "../customers/types";
import { requestedUrls, stubApiFetch, type ApiResponder } from "../testing";
import CustomerRelationsPage from "./CustomerRelationsPage.vue";

const PAGE_SIZE = 20;
const DIRECTORY_SIZE = 120;

function makeCustomer(id: number): CustomerListItem {
  return {
    id,
    username: `customer${id}`,
    real_name: `客户${id}`,
    customer_level: "普通",
    risk_level: "C3",
  };
}

const ALL_CUSTOMERS = Array.from({ length: DIRECTORY_SIZE }, (_, index) => makeCustomer(index + 1));

function directoryResponder() {
  return (url: string) => {
    if (!url.includes("/api/internal/customers")) return undefined;
    const query = new URLSearchParams(url.split("?")[1] ?? "");
    const page = Number(query.get("page") ?? 1);
    const pageSize = Number(query.get("page_size") ?? PAGE_SIZE);
    const offset = (page - 1) * pageSize;
    return {
      items: ALL_CUSTOMERS.slice(offset, offset + pageSize),
      total: ALL_CUSTOMERS.length,
      page,
      page_size: pageSize,
    };
  };
}

/** 一位客户都没有的目录。 */
const EMPTY_DIRECTORY: ApiResponder = (url) =>
  url.includes("/api/internal/customers")
    ? { items: [], total: 0, page: 1, page_size: PAGE_SIZE }
    : undefined;

let activeWrapper: VueWrapper | null = null;
let fetchMock: ReturnType<typeof stubApiFetch>;

async function mountPage(respond: ApiResponder = directoryResponder()): Promise<VueWrapper> {
  fetchMock = stubApiFetch(respond);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/relations", component: CustomerRelationsPage },
      {
        path: "/operation-advice/:adviceId",
        name: "operation-advice-review",
        component: { template: "<div />" },
      },
    ],
  });
  await router.push("/relations");
  await router.isReady();

  activeWrapper = mount(CustomerRelationsPage, {
    global: { plugins: [ElementPlus, router] },
  });
  await flushPromises();
  return activeWrapper;
}

function tableRows(page: VueWrapper) {
  return page.get('[data-testid="relations-table"]').findAll("tbody tr");
}

describe("客户关系的名下客户列表", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
    vi.unstubAllGlobals();
  });

  it("shows the first page the server gave and how many there are in total", async () => {
    const page = await mountPage();

    expect(page.get('[data-testid="pagination-total"]').text()).toBe("共 120 条");
    expect(tableRows(page)).toHaveLength(PAGE_SIZE);
    expect(tableRows(page)[0].text()).toContain("客户1");
  });

  it("replaces the table with the next page instead of keeping the first one", async () => {
    const page = await mountPage();

    await page.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(requestedUrls(fetchMock, "page=2&page_size=20")).not.toHaveLength(0);
    expect(tableRows(page)).toHaveLength(PAGE_SIZE);
    expect(tableRows(page)[0].text()).toContain("客户21");
    // 第 2 页是 客户21–40：上一页的人一个都不该还在表里。
    expect(page.get('[data-testid="relations-table"]').text()).not.toContain("客户1");
  });

  it("says so when there is no customer to show", async () => {
    const page = await mountPage(EMPTY_DIRECTORY);

    expect(page.get('[data-testid="relations-empty"]').text()).toContain("名下还没有客户");
    expect(page.find('[data-testid="relations-table"]').exists()).toBe(false);
    expect(page.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("gives the advice picker the whole directory, not just this page", async () => {
    await mountPage();

    // 选中框要的是全部客户：目录按 100 条一页给，120 位客户因此要翻到第 2 页。
    // 只取第一页的话，第 101 位之后的客户在选中框里根本不存在。
    expect(requestedUrls(fetchMock, "page=1&page_size=100")).not.toHaveLength(0);
    expect(requestedUrls(fetchMock, "page=2&page_size=100")).not.toHaveLength(0);
  });
});
