// 规则管理列表接分页。
//
// 规则按编号升序，排序键本来就稳定，所以没有排序控件；要盯的是分页与写操作的配合：
// 启停失败后重取的是**当前这一页**（回到第 1 页会让人以为规则变少了），以及总数说的是
// 全部规则而不是本页条数。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type PageQuery } from "@wealth/shared";
import { RISK_OFFICER } from "../auth/identity";
import { useAuthStore } from "../stores/auth";
import type { RiskRule } from "./types";

const { listRiskRules, setRiskRuleEnabled } = vi.hoisted(() => ({
  listRiskRules: vi.fn(),
  setRiskRuleEnabled: vi.fn(),
}));

vi.mock("./api", () => ({
  listRiskRules,
  setRiskRuleEnabled,
  setRiskRuleThreshold: vi.fn(),
}));

import RiskRulesTab from "./RiskRulesTab.vue";

const PAGE_SIZE = 10;
const TOTAL = 25;

function makeRule(overrides: Partial<RiskRule> = {}): RiskRule {
  return {
    id: 1,
    rule_code: "R001",
    rule_name: "单笔大额交易",
    category: "大额交易",
    description: "单笔交易金额达到阈值",
    field: "amount",
    field_label: "交易金额",
    operator: "gte",
    operator_label: "大于等于",
    threshold: { value: "50000" },
    threshold_text: "50000",
    window_hours: null,
    alert_level: "轻度",
    weight: 1,
    enabled: true,
    ...overrides,
  };
}

function makePage(
  items: RiskRule[],
  total: number,
  query: PageQuery = { page: 1, page_size: PAGE_SIZE },
) {
  return { items, total, page: query.page, page_size: query.page_size };
}

let activeWrapper: VueWrapper | null = null;

async function mountTab(): Promise<VueWrapper> {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().currentEmployee = { real_name: "周风控", employee_role: RISK_OFFICER };

  activeWrapper = mount(RiskRulesTab, { global: { plugins: [ElementPlus, pinia] } });
  await flushPromises();
  return activeWrapper;
}

function lastQuery(): PageQuery {
  return listRiskRules.mock.calls.at(-1)![0] as PageQuery;
}

describe("RiskRulesTab 的分页", () => {
  beforeEach(() => {
    listRiskRules.mockReset();
    setRiskRuleEnabled.mockReset();
    listRiskRules.mockResolvedValue(makePage([], 0));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("asks for the first page and shows how many rules there are in total", async () => {
    listRiskRules.mockResolvedValue(makePage([makeRule()], TOTAL));
    const wrapper = await mountTab();

    expect(listRiskRules).toHaveBeenCalledWith({ page: 1, page_size: PAGE_SIZE });
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 25 条");
  });

  it("turns the page and shows the rules of the page it landed on", async () => {
    listRiskRules.mockImplementation((query: PageQuery) =>
      Promise.resolve(
        makePage(
          [makeRule({ rule_code: query.page === 1 ? "R001" : "R021" })],
          TOTAL,
          query,
        ),
      ),
    );
    const wrapper = await mountTab();

    expect(wrapper.get('[data-testid="rules-table"]').text()).toContain("R001");

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(lastQuery().page).toBe(2);
    expect(wrapper.get('[data-testid="rules-table"]').text()).toContain("R021");
    expect(wrapper.get('[data-testid="rules-table"]').text()).not.toContain("R001");
  });

  it("re-reads the page it is on when toggling a rule fails", async () => {
    // 失败后回到第 1 页，人看到的会是另一批规则——像是规则变少了，而不是这次没改成。
    listRiskRules.mockImplementation((query: PageQuery) =>
      Promise.resolve(makePage([makeRule()], TOTAL, query)),
    );
    setRiskRuleEnabled.mockRejectedValue(
      new ApiError({ code: 500, message: "服务内部错误", data: null, trace_id: "t-1" }),
    );
    const wrapper = await mountTab();

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    await wrapper.get('[data-testid="rule-enabled"]').trigger("click");
    await flushPromises();

    expect(setRiskRuleEnabled).toHaveBeenCalledWith(1, false);
    expect(lastQuery().page).toBe(2);
    // 失败原因要留在页面上：随后的重取若把它清掉，人就只看到一个退回去的开关。
    expect(wrapper.get('[data-testid="rule-error"]').text()).toContain("服务内部错误");
  });

  it("keeps an explanation and the pager on a page that turned out to be empty", async () => {
    listRiskRules.mockImplementation((query: PageQuery) =>
      Promise.resolve(makePage(query.page === 1 ? [makeRule()] : [], TOTAL, query)),
    );
    const wrapper = await mountTab();

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="rules-table"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(true);
  });

  it("leaves the reason on screen when the load fails", async () => {
    listRiskRules.mockRejectedValue(new Error("boom"));
    const wrapper = await mountTab();

    expect(wrapper.get('[data-testid="rule-error"]').text()).toContain("规则列表加载失败");
    expect(wrapper.find('[data-testid="rules-table"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });
});
