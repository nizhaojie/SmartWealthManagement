// 详情页只渲染客户送达视图以内的东西（ADR-0016）。
// 夹具里多塞一份内部字段：接口不会返回它们，这里证明页面也不渲染它们——
// 裁剪的落点是服务端，本页不靠「模板里没写」兜底。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

const { getReleasedPlan } = vi.hoisted(() => ({ getReleasedPlan: vi.fn() }));

vi.mock("./api", () => ({ getReleasedPlan }));

import AdvisoryPlanDetailPage from "./AdvisoryPlanDetailPage.vue";

const Blank = { render: () => h("div") };
const DAY_MS = 24 * 60 * 60 * 1000;
const RELEASED_AT = new Date(Date.now() - 3 * DAY_MS).toISOString();

const PLAN = {
  id: 12,
  advisor_name: "李文",
  candidates: [
    {
      product_code: "F000001",
      product_name: "天枢货币基金",
      product_type: "货币基金",
      risk_level: "R1",
      expected_return: "2.1000",
      term_days: 0,
      composite_score: 88.5,
      reason: "客户风险承受等级为 C3，符合画像记录的产品偏好",
    },
  ],
  allocation_suggestion: { 债券: 60, 股票: 40 },
  released_at: RELEASED_AT,
  disclaimer: "本方案由理财顾问出具，仅供参考",
  // 以下都不在客户送达视图以内。
  warnings: [{ code: "CONCENTRATION", message: "集中度偏高，请核实后再采用" }],
  score_breakdown: [{ dimension: "收益", score: 90, weight: 0.4, contribution: 36 }],
  content_classification: "投顾内容",
  customer_id: 7,
  advisor_id: 2,
  draft_id: 3,
};

let router: Router;
let activeWrapper: VueWrapper | null = null;

async function mountPage(): Promise<VueWrapper> {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/advisory", name: "advisory", component: Blank },
      { path: "/advisory/plans/:finalId", name: "advisory-plan", component: Blank },
    ],
  });
  await router.push({ name: "advisory-plan", params: { finalId: "12" } });
  await router.isReady();

  activeWrapper = mount(AdvisoryPlanDetailPage, {
    global: { plugins: [ElementPlus, router] },
  });
  await flushPromises();
  return activeWrapper;
}

describe("AdvisoryPlanDetailPage", () => {
  beforeEach(() => {
    getReleasedPlan.mockReset();
    getReleasedPlan.mockResolvedValue(PLAN);
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("renders 出具顾问、放行时间、时效提示、配置建议、产品清单与免责声明", async () => {
    const wrapper = await mountPage();

    expect(getReleasedPlan).toHaveBeenCalledWith("12");
    expect(wrapper.get('[data-testid="plan-advisor"]').text()).toContain("出具顾问：李文");
    expect(wrapper.get('[data-testid="plan-released-at"]').text()).toContain("放行时间：");

    const timeliness = wrapper.get('[data-testid="plan-timeliness"]').text();
    expect(timeliness).toContain("出具于");
    expect(timeliness).toContain("（3 天前）");
    expect(timeliness).toContain("本方案基于出具时点的画像与市场数据");

    expect(wrapper.get('[data-testid="plan-allocation"]').text()).toContain("债券：60%");
    expect(wrapper.get('[data-testid="plan-allocation"]').text()).toContain("股票：40%");

    const products = wrapper.get('[data-testid="plan-candidates"]').text();
    expect(products).toContain("F000001");
    expect(products).toContain("天枢货币基金");
    expect(products).toContain("2.1000");

    expect(wrapper.get('[data-testid="plan-disclaimer"]').text()).toBe(
      "本方案由理财顾问出具，仅供参考",
    );
  });

  it("does not render 综合得分、排序依据与推荐理由", async () => {
    const wrapper = await mountPage();
    const text = wrapper.text();

    expect(text).not.toContain("综合得分");
    expect(text).not.toContain("排序依据");
    expect(text).not.toContain("推荐理由");
    expect(text).not.toContain("88.5");
    expect(text).not.toContain("客户风险承受等级");
    // 预警的措辞是写给顾问的。
    expect(text).not.toContain("请核实后再采用");
  });

  it("returns to 我的方案 with the back entry", async () => {
    const wrapper = await mountPage();

    await wrapper.get('button[name="back-to-plans"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory");
    expect(router.currentRoute.value.path).toBe("/advisory");
  });
});
