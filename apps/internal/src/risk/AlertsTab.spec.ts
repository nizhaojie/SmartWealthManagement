// 预警列表页：筛选、排序与翻页三者的联动。
//
// 这一页原先在本地对拉回来的全量结果排序（`sortAlerts`）。分页之后前端手里只有当前页，
// 所以这里盯的是三件在改造中最容易漏的事：
//   1. 排序方式真的发给服务端了（不是排完本页就当排过了）；
//   2. 翻页时筛选与排序原样带走——少了它们，第 2 页会变成「全部预警的第 2 页」，
//      与页面上还留着的筛选条件对不上，而看起来完全正常；
//   3. 改筛选或改排序都回到第一页：停在第 3 页看到的空表不是新条件的结果。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import type { PageQuery } from "@wealth/shared";
import type { AlertFilters } from "./api";
import type { AlertSummary } from "./types";

const { listAlerts } = vi.hoisted(() => ({ listAlerts: vi.fn() }));

vi.mock("./api", () => ({ listAlerts }));

import AlertsTab from "./AlertsTab.vue";

const PAGE_SIZE = 20;
const TOTAL = 45;

function makeAlert(overrides: Partial<AlertSummary> = {}): AlertSummary {
  return {
    id: 1,
    customer_id: 1,
    customer_name: "王客户",
    alert_type: "大额转账",
    alert_level: "重度",
    confidence: 0.9,
    rule_codes: ["R001"],
    rule_count: 1,
    transaction_ids: [],
    status: "未处理",
    source: "客户发起",
    created_at: "2026-09-18T10:00:00",
    work_order_id: null,
    work_order_status: null,
    ...overrides,
  };
}

function makePage(
  items: AlertSummary[],
  total: number,
  query: PageQuery = { page: 1, page_size: PAGE_SIZE },
) {
  return { items, total, page: query.page, page_size: query.page_size };
}

let router: Router;
let activeWrapper: VueWrapper | null = null;

async function mountTab(): Promise<VueWrapper> {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { template: "<div />" } },
      {
        path: "/risk-monitoring/alerts/:alertId",
        name: "risk-alert-detail",
        component: { template: "<div />" },
      },
    ],
  });
  await router.push("/");
  await router.isReady();

  activeWrapper = mount(AlertsTab, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return activeWrapper;
}

/** 表单里的筛选与排序都走真实的控件：点开下拉，再点中那一项。 */
async function chooseOption(fieldLabel: string, optionLabel: string): Promise<void> {
  const field = activeWrapper!.findAll(".filters__field").find(
    (item) => item.get(".filters__label").text() === fieldLabel,
  );
  expect(field, `找不到「${fieldLabel}」这一栏`).toBeTruthy();

  await field!.get(".el-select").trigger("click");
  await flushPromises();

  const option = [
    ...document.querySelectorAll<HTMLElement>(".el-select-dropdown__item"),
  ].find((item) => item.textContent?.trim() === optionLabel);
  expect(option, `找不到选项「${optionLabel}」`).toBeTruthy();

  option!.click();
  await flushPromises();
}

async function turnPage(): Promise<void> {
  await activeWrapper!.get(".pagination-bar .btn-next").trigger("click");
  await flushPromises();
}

function lastCall(): [AlertFilters, PageQuery] {
  return listAlerts.mock.calls.at(-1) as [AlertFilters, PageQuery];
}

function tableText(): string {
  return activeWrapper!.get('[data-testid="alerts-table"]').text();
}

describe("AlertsTab 的分页", () => {
  beforeEach(() => {
    listAlerts.mockReset();
    listAlerts.mockResolvedValue(makePage([], 0));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("asks for the first page and shows how many there are in total", async () => {
    listAlerts.mockResolvedValue(makePage([makeAlert()], TOTAL));
    const wrapper = await mountTab();

    expect(listAlerts).toHaveBeenCalledWith(
      expect.objectContaining({ orderBy: "created_desc" }),
      { page: 1, page_size: PAGE_SIZE },
    );
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
  });

  it("turns the page and shows the rows of the page it landed on", async () => {
    listAlerts.mockImplementation((_filters: AlertFilters, query: PageQuery) =>
      Promise.resolve(
        makePage(
          [makeAlert({ id: query.page, alert_type: query.page === 1 ? "第一页" : "第二页" })],
          TOTAL,
          query,
        ),
      ),
    );
    const wrapper = await mountTab();

    expect(tableText()).toContain("第一页");

    await turnPage();

    expect(lastCall()[1]).toEqual({ page: 2, page_size: PAGE_SIZE });
    expect(tableText()).toContain("第二页");
    expect(tableText()).not.toContain("第一页");
    // 总数不随翻页变：它是过滤后的总数，不是本页条数。
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
  });

  it("carries the filters and the sort into the next page instead of silently dropping them", async () => {
    listAlerts.mockImplementation((_filters: AlertFilters, query: PageQuery) =>
      Promise.resolve(makePage([makeAlert()], TOTAL, query)),
    );
    await mountTab();

    await chooseOption("等级", "重度");
    expect(lastCall()[0].alertLevel).toBe("重度");
    expect(lastCall()[1].page).toBe(1);

    await turnPage();

    expect(lastCall()[0].alertLevel).toBe("重度");
    expect(lastCall()[0].orderBy).toBe("created_desc");
    expect(lastCall()[1].page).toBe(2);
  });

  it("sends the sort the officer picked to the server and goes back to the first page", async () => {
    // 排序下推是这一批改造的重点：本地排序会让「按等级」只排得动当前页。
    listAlerts.mockImplementation((_filters: AlertFilters, query: PageQuery) =>
      Promise.resolve(makePage([makeAlert()], TOTAL, query)),
    );
    await mountTab();

    await turnPage();
    expect(lastCall()[1].page).toBe(2);

    await chooseOption("排序", "按等级（重到轻）");

    expect(lastCall()[0].orderBy).toBe("level_desc");
    expect(lastCall()[1].page).toBe(1);
  });

  it("keeps an explanation and the pager on a page that turned out to be empty", async () => {
    listAlerts.mockImplementation((_filters: AlertFilters, query: PageQuery) =>
      Promise.resolve(makePage(query.page === 1 ? [makeAlert()] : [], TOTAL, query)),
    );
    const wrapper = await mountTab();

    await turnPage();

    expect(wrapper.find('[data-testid="alerts-table"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="alerts-empty"]').text()).toContain("暂无预警");
    // 空页不是「没有预警」：撤掉分页条，人就困在这一页上了。
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(true);
  });

  it("leaves the reason on screen instead of a stale page when the load fails", async () => {
    listAlerts.mockRejectedValue(new Error("boom"));
    const wrapper = await mountTab();

    expect(wrapper.get('[data-testid="alert-error"]').text()).toContain("预警列表加载失败");
    expect(wrapper.find('[data-testid="alerts-table"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("writes the filtered total back to the inspector, not the number of rows on this page", async () => {
    listAlerts.mockResolvedValue(makePage([makeAlert()], TOTAL));
    const wrapper = await mountTab();

    const summaries = wrapper.emitted("summary");
    expect(summaries).toBeTruthy();
    expect(summaries!.at(-1)![0]).toMatchObject({ count: TOTAL });
  });
});
