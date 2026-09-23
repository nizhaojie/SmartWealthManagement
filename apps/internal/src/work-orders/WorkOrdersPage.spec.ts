// 工单列表：带筛选的表格接分页（ADR-0024）。
//
// 要盯的是三件事：翻页带不带筛选、改筛选回不回第一页、`total` 是过滤后的总数而不是
// 本页条数（后者会随翻页变，看起来也像个总数）。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { PageQuery } from "@wealth/shared";
import { stubApiFetch } from "../testing";
import type { WorkOrder } from "./types";

const { listWorkOrders } = vi.hoisted(() => ({ listWorkOrders: vi.fn() }));

vi.mock("./api", () => ({
  listWorkOrders,
  // 建单表单从同一个模块取它，用例不展开建单，但 import 要有东西落。
  createExternalWorkOrder: vi.fn(),
}));

import WorkOrdersPage from "./WorkOrdersPage.vue";

const PAGE_SIZE = 10;
const TOTAL = 45;

function makeOrder(overrides: Partial<WorkOrder> = {}): WorkOrder {
  return {
    id: 1,
    work_order_no: "WO20260918001",
    order_type: "客户投诉",
    sub_type: null,
    alert_id: null,
    customer_id: null,
    handler_id: 4,
    handler_name: "周风控",
    status: "待处理",
    current_node: "待处理",
    priority: "普通",
    biz_content: null,
    handle_reason: "客户投诉收益到账延迟",
    handle_result: null,
    created_at: "2026-09-18T10:00:00",
    updated_at: "2026-09-18T10:00:00",
    ...overrides,
  };
}

function makePage(
  items: WorkOrder[],
  total: number,
  query: PageQuery = { page: 1, page_size: PAGE_SIZE },
) {
  return { items, total, page: query.page, page_size: query.page_size };
}

let activeWrapper: VueWrapper | null = null;

async function mountPage(): Promise<VueWrapper> {
  // 客户筛选的下拉拉的是完整目录（另一个模块的接口），这里给它一个空目录。
  stubApiFetch();
  setActivePinia(createPinia());
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/work-orders", component: WorkOrdersPage },
      {
        path: "/work-orders/:workOrderId",
        name: "work-order-detail",
        component: { template: "<div />" },
      },
    ],
  });
  await router.push("/work-orders");
  await router.isReady();

  activeWrapper = mount(WorkOrdersPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return activeWrapper;
}

async function chooseStatus(label: string): Promise<void> {
  await activeWrapper!.get('[data-testid="work-order-status-filter"]').trigger("click");
  await flushPromises();

  const option = [...document.querySelectorAll<HTMLElement>(".el-select-dropdown__item")].find(
    (item) => item.textContent?.trim() === label,
  );
  expect(option, `找不到选项「${label}」`).toBeTruthy();

  option!.click();
  await flushPromises();
}

function lastFilters(): Record<string, unknown> {
  return listWorkOrders.mock.calls.at(-1)![0] as Record<string, unknown>;
}

function lastQuery(): PageQuery {
  return listWorkOrders.mock.calls.at(-1)![1] as PageQuery;
}

function tableText(): string {
  return activeWrapper!.get('[data-testid="work-orders-table"]').text();
}

describe("工单列表的分页", () => {
  beforeEach(() => {
    listWorkOrders.mockReset();
    listWorkOrders.mockResolvedValue(makePage([], 0));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
    vi.unstubAllGlobals();
  });

  it("asks for the first page and shows how many there are in total", async () => {
    listWorkOrders.mockResolvedValue(makePage([makeOrder()], TOTAL));
    const wrapper = await mountPage();

    expect(listWorkOrders).toHaveBeenCalledWith({}, { page: 1, page_size: PAGE_SIZE });
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
  });

  it("turns the page and carries the status filter along", async () => {
    listWorkOrders.mockImplementation((_filters, query: PageQuery) =>
      Promise.resolve(
        makePage(
          [makeOrder({ handle_reason: query.page === 1 ? "第一页" : "第二页" })],
          TOTAL,
          query,
        ),
      ),
    );
    await mountPage();

    await chooseStatus("处理中");
    expect(lastFilters()).toEqual({ status: "处理中", customerId: undefined, alertId: undefined });
    expect(lastQuery().page).toBe(1);

    await activeWrapper!.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    // 少了筛选，第 2 页会变成「全部工单的第 2 页」，与筛选框里留着的状态对不上。
    expect(lastFilters().status).toBe("处理中");
    expect(lastQuery().page).toBe(2);
    expect(tableText()).toContain("第二页");
    expect(tableText()).not.toContain("第一页");
  });

  it("goes back to the first page when the filter changes", async () => {
    listWorkOrders.mockImplementation((_filters, query: PageQuery) =>
      Promise.resolve(makePage([makeOrder()], TOTAL, query)),
    );
    await mountPage();

    await activeWrapper!.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(lastQuery().page).toBe(2);

    await chooseStatus("已完成");

    expect(lastQuery().page).toBe(1);
  });

  it("keeps an explanation and the pager on a page that turned out to be empty", async () => {
    listWorkOrders.mockImplementation((_filters, query: PageQuery) =>
      Promise.resolve(makePage(query.page === 1 ? [makeOrder()] : [], TOTAL, query)),
    );
    const wrapper = await mountPage();

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="work-orders-table"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="work-orders-empty"]').text()).toContain("暂无工单");
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(true);
  });

  it("shows no pager at all when there is no work order to page through", async () => {
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="work-orders-empty"]').text()).toContain("暂无工单");
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("leaves the reason on screen when the load fails", async () => {
    listWorkOrders.mockRejectedValue(new Error("boom"));
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="work-order-error"]').text()).toContain("工单列表加载失败");
    expect(wrapper.find('[data-testid="work-orders-table"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });
});
