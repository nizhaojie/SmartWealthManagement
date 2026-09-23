// 风险关注列表：一个只读列表接分页。
//
// 它没有排序控件（服务端固定「最近的在前」），要盯的是分页与筛选的联动：翻页带不带
// 类型筛选、改筛选回不回第一页、`total` 是过滤后的总数。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PageQuery } from "@wealth/shared";
import type { RiskFocus } from "./types";

const { listRiskFocus } = vi.hoisted(() => ({ listRiskFocus: vi.fn() }));

vi.mock("./api", () => ({ listRiskFocus }));

import RiskFocusTab from "./RiskFocusTab.vue";

const PAGE_SIZE = 10;
const TOTAL = 45;

function makeFocus(overrides: Partial<RiskFocus> = {}): RiskFocus {
  return {
    id: 1,
    customer_id: 1,
    customer_name: "王客户",
    focus_type: "风控预警",
    severity: "重度",
    reason: "风控预警（重度）：命中规则 R001",
    source: "risk-monitoring-agent",
    trace_id: "trace-1",
    occurred_at: "2026-09-18T10:00:00",
    ...overrides,
  };
}

function makePage(
  items: RiskFocus[],
  total: number,
  query: PageQuery = { page: 1, page_size: PAGE_SIZE },
) {
  return { items, total, page: query.page, page_size: query.page_size };
}

let activeWrapper: VueWrapper | null = null;

async function mountTab(): Promise<VueWrapper> {
  activeWrapper = mount(RiskFocusTab, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return activeWrapper;
}

async function chooseFocusType(label: string): Promise<void> {
  await activeWrapper!.get('[data-testid="focus-type-filter"]').trigger("click");
  await flushPromises();

  const option = [
    ...document.querySelectorAll<HTMLElement>(".el-select-dropdown__item"),
  ].find((item) => item.textContent?.trim() === label);
  expect(option, `找不到选项「${label}」`).toBeTruthy();

  option!.click();
  await flushPromises();
}

function lastQuery(): PageQuery {
  return listRiskFocus.mock.calls.at(-1)![1] as PageQuery;
}

function tableText(): string {
  return activeWrapper!.get('[data-testid="focus-table"]').text();
}

describe("RiskFocusTab 的分页", () => {
  beforeEach(() => {
    listRiskFocus.mockReset();
    listRiskFocus.mockResolvedValue(makePage([], 0));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("asks for the first page and shows how many there are in total", async () => {
    listRiskFocus.mockResolvedValue(makePage([makeFocus()], TOTAL));
    const wrapper = await mountTab();

    expect(listRiskFocus).toHaveBeenCalledWith({}, { page: 1, page_size: PAGE_SIZE });
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
  });

  it("turns the page and carries the type filter along", async () => {
    listRiskFocus.mockImplementation((_filters: { focusType?: string }, query: PageQuery) =>
      Promise.resolve(
        makePage(
          [makeFocus({ reason: query.page === 1 ? "第一页" : "第二页" })],
          TOTAL,
          query,
        ),
      ),
    );
    await mountTab();

    await chooseFocusType("高风险意图");
    expect(listRiskFocus.mock.calls.at(-1)![0]).toEqual({ focusType: "高风险意图" });
    expect(lastQuery().page).toBe(1);

    await activeWrapper!.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    // 少了筛选，第 2 页会变成「全部风险关注的第 2 页」，与页面上留着的筛选对不上。
    expect(listRiskFocus.mock.calls.at(-1)![0]).toEqual({ focusType: "高风险意图" });
    expect(lastQuery().page).toBe(2);
    expect(tableText()).toContain("第二页");
    expect(tableText()).not.toContain("第一页");
  });

  it("goes back to the first page when the type filter changes", async () => {
    listRiskFocus.mockImplementation((_filters: { focusType?: string }, query: PageQuery) =>
      Promise.resolve(makePage([makeFocus()], TOTAL, query)),
    );
    await mountTab();

    await activeWrapper!.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(lastQuery().page).toBe(2);

    await chooseFocusType("风控预警");

    expect(lastQuery().page).toBe(1);
  });

  it("keeps an explanation and the pager on a page that turned out to be empty", async () => {
    listRiskFocus.mockImplementation((_filters: { focusType?: string }, query: PageQuery) =>
      Promise.resolve(makePage(query.page === 1 ? [makeFocus()] : [], TOTAL, query)),
    );
    const wrapper = await mountTab();

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="focus-table"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="focus-empty"]').text()).toContain("暂无风险关注");
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(true);
  });

  it("leaves the reason on screen when the load fails", async () => {
    listRiskFocus.mockRejectedValue(new Error("boom"));
    const wrapper = await mountTab();

    expect(wrapper.get('[data-testid="focus-error"]').text()).toContain("风险关注加载失败");
    expect(wrapper.find('[data-testid="focus-table"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });
});
