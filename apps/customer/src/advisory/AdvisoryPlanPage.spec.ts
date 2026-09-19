// 「我的方案」页的三种首屏：有定稿 / 只有请求 / 都无。
// 两个分区（已放行方案、方案请求进度）不合成一条时间线，空状态也分两级（Q6、Q13）。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ApiError } from "@wealth/shared";
import type { AdvisoryRequest, ReleasedPlan } from "./types";

const { listReleasedPlans, listAdvisoryRequests } = vi.hoisted(() => ({
  listReleasedPlans: vi.fn(),
  listAdvisoryRequests: vi.fn(),
}));

vi.mock("./api", () => ({ listReleasedPlans, listAdvisoryRequests }));

import AdvisoryPlanPage from "./AdvisoryPlanPage.vue";

const Blank = { render: () => h("div") };

function makePlan(overrides: Partial<ReleasedPlan> = {}): ReleasedPlan {
  return {
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
      },
      {
        product_code: "F000002",
        product_name: "天玑债券基金",
        product_type: "债券基金",
        risk_level: "R2",
        expected_return: "3.5000",
        term_days: 180,
      },
    ],
    allocation_suggestion: { 债券: 60 },
    released_at: "2026-09-10T09:00:00",
    disclaimer: "本方案由理财顾问出具，仅供参考",
    ...overrides,
  };
}

function makeRequest(overrides: Partial<AdvisoryRequest> = {}): AdvisoryRequest {
  return {
    id: 1,
    request_no: "AR20260915A1B2C3",
    status: "待处理",
    filters: { product_type: "债券基金" },
    submitted_at: "2026-09-15T08:30:00",
    ...overrides,
  };
}

let router: Router;
let activeWrapper: VueWrapper | null = null;

async function mountPage(): Promise<VueWrapper> {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/advisory", name: "advisory", component: Blank },
      { path: "/advisory/plans/:finalId", name: "advisory-plan", component: Blank },
      { path: "/products", name: "products", component: Blank },
    ],
  });
  await router.push("/advisory");
  await router.isReady();
  activeWrapper = mount(AdvisoryPlanPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return activeWrapper;
}

describe("AdvisoryPlanPage", () => {
  beforeEach(() => {
    listReleasedPlans.mockReset();
    listAdvisoryRequests.mockReset();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("summarises each released plan with 出具时间、出具顾问 and 产品数", async () => {
    listReleasedPlans.mockResolvedValue({ plans: [makePlan()] });
    listAdvisoryRequests.mockResolvedValue({ requests: [] });
    const wrapper = await mountPage();

    const row = wrapper.get('[data-testid="released-plan"]');
    expect(row.text()).toContain("出具顾问：李文");
    expect(row.text()).toContain("产品数：2");
    expect(row.text()).toContain("出具时间：");
    expect(wrapper.findAll('[data-testid="released-plan"]')).toHaveLength(1);
    // 没有任何请求时不该出现请求分区，也不该出现引导空状态。
    expect(wrapper.find('[data-testid="advisory-requests"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("还没有提交过方案请求");
  });

  it("renders the 方案请求进度 when there is no released plan yet", async () => {
    listReleasedPlans.mockResolvedValue({ plans: [] });
    listAdvisoryRequests.mockResolvedValue({ requests: [makeRequest()] });
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="released-plans"]').exists()).toBe(false);
    const request = wrapper.get('[data-testid="advisory-request"]').text();
    expect(request).toContain("待处理");
    expect(request).toContain("AR20260915A1B2C3");
    expect(request).toContain("债券基金");
    // 请求已经在等顾问了，就不该再说「还没有提交过方案请求」。
    expect(wrapper.text()).not.toContain("还没有提交过方案请求");
  });

  it("guides to 产品筛选 when there is neither a plan nor a request", async () => {
    listReleasedPlans.mockResolvedValue({ plans: [] });
    listAdvisoryRequests.mockResolvedValue({ requests: [] });
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="plans-empty"]').text()).toContain("还没有提交过方案请求");

    await wrapper.get('button[name="go-products"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/products");
  });

  it("opens a plan at its own route", async () => {
    listReleasedPlans.mockResolvedValue({ plans: [makePlan({ id: 12 })] });
    listAdvisoryRequests.mockResolvedValue({ requests: [] });
    const wrapper = await mountPage();

    await wrapper.get('[data-testid="released-plan"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory-plan");
    expect(router.currentRoute.value.params.finalId).toBe("12");
  });

  // 「拉取失败」不是「什么都没有」：把接口故障说成「你还没提过请求」会让客户去重复提交。
  it("does not present a failed plan load as an empty state", async () => {
    listReleasedPlans.mockRejectedValue(
      new ApiError({ code: 500, message: "服务内部错误", data: null, trace_id: "" }),
    );
    listAdvisoryRequests.mockResolvedValue({ requests: [] });
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="plans-error"]').text()).toContain("服务内部错误");
    expect(wrapper.find('[data-testid="plans-empty"]').exists()).toBe(false);
  });
});
