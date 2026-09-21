// 「我的建议」页：四种状态各自成区、接受失败时渲染原因且建议仍留在待决定区。
// 失败语义来自 #07：接受是一次原子操作，受理校验不过就整条失败，建议不落进任何终态。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ApiError } from "@wealth/shared";
import type { OperationAdvice } from "./types";

const { listMyAdvice, decideAdvice } = vi.hoisted(() => ({
  listMyAdvice: vi.fn(),
  decideAdvice: vi.fn(),
}));

vi.mock("./api", () => ({ listMyAdvice, decideAdvice }));

import AdvicePage from "./AdvicePage.vue";

const Blank = { render: () => h("div") };

function apiError(code: number, message: string): ApiError {
  return new ApiError({ code, message, data: null, trace_id: "t-1" });
}

function makeAdvice(overrides: Partial<OperationAdvice> = {}): OperationAdvice {
  return {
    id: 1,
    product_code: "F000002",
    product_name: "天玑债券基金",
    direction: "申购",
    amount: "50000.00",
    reason: "你的债券配置偏低，这笔申购把比例补回来",
    status: "待客户决定",
    released_at: "2026-09-21T09:00:00",
    expires_at: "2026-09-28T09:00:00",
    decision: null,
    decided_at: null,
    disclaimer: "本建议由理财顾问出具，仅供参考",
    ...overrides,
  };
}

let pinia: Pinia;
let router: Router;
let activeWrapper: VueWrapper | null = null;

async function mountPage(): Promise<VueWrapper> {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/operation-advice", name: "operation-advice", component: Blank },
      { path: "/risk-assessment", name: "risk-assessment", component: Blank },
      { path: "/trading", name: "trading", component: Blank },
    ],
  });
  await router.push("/operation-advice");
  await router.isReady();
  activeWrapper = mount(AdvicePage, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  return activeWrapper;
}

async function accept(wrapper: VueWrapper, name = "accept-advice"): Promise<void> {
  await wrapper.get(`button[name="${name}"]`).trigger("click");
  await flushPromises();
}

describe("AdvicePage", () => {
  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    listMyAdvice.mockReset();
    decideAdvice.mockReset();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("groups the advice into the four states", async () => {
    listMyAdvice.mockResolvedValue({
      advice: [
        makeAdvice({ id: 1, status: "待客户决定" }),
        makeAdvice({ id: 2, status: "已接受", decision: "接受", decided_at: "2026-09-22T10:00:00" }),
        makeAdvice({ id: 3, status: "已拒绝", decision: "拒绝", decided_at: "2026-09-22T11:00:00" }),
        makeAdvice({ id: 4, status: "已过期" }),
      ],
    });
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="advice-pending"]').text()).toContain("50000.00");
    expect(wrapper.find('[data-testid="advice-accepted"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="advice-rejected"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="advice-expired"]').exists()).toBe(true);
    // 已决定的三类各自成区，不接受也不拒绝。
    expect(wrapper.findAll('button[name="accept-advice"]')).toHaveLength(1);
    // 免责声明是客户送达视图的一部分（#07 的十二个字段之一），送到就得渲染出来。
    expect(wrapper.get('[data-testid="advice-disclaimer"]').text()).toContain("仅供参考");
  });

  it("leaves no blank when nothing has been delivered yet", async () => {
    listMyAdvice.mockResolvedValue({ advice: [] });
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="advice-empty"]').text()).toContain("还没有收到操作建议");
    expect(wrapper.find('[data-testid="advice-pending"]').exists()).toBe(false);
  });

  it("keeps the advice in the pending group when the balance is short", async () => {
    listMyAdvice.mockResolvedValue({ advice: [makeAdvice()] });
    decideAdvice.mockRejectedValue(apiError(400, "可用余额不足，还差 1200.00 元"));
    const wrapper = await mountPage();

    await accept(wrapper);

    expect(wrapper.get('[data-testid="advice-failure"]').text()).toContain(
      "可用余额不足，还差 1200.00 元",
    );
    // 受理校验没过：建议仍在待客户决定，客户补足余额后可以再来一次。
    expect(wrapper.get('[data-testid="advice-pending"]').text()).toContain("天玑债券基金");
    expect(wrapper.findAll('[data-testid="advice-item"]')).toHaveLength(1);
    expect(wrapper.find('[data-testid="advice-accepted"]').exists()).toBe(false);
    // 失败不刷新列表：刷新会把一条什么都没发生的建议说成别的状态。
    expect(listMyAdvice).toHaveBeenCalledTimes(1);
  });

  it("links to 风险测评 when the acceptance fails for a missing assessment", async () => {
    listMyAdvice.mockResolvedValue({ advice: [makeAdvice()] });
    decideAdvice.mockRejectedValue(apiError(403, "请先完成风险测评"));
    const wrapper = await mountPage();

    await accept(wrapper);

    expect(wrapper.get('[data-testid="advice-failure"]').text()).toContain("请先完成风险测评");

    await wrapper.get('[data-testid="go-risk-assessment"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/risk-assessment");
  });

  it("renders the reason when the acceptance fails for a product above the grade", async () => {
    listMyAdvice.mockResolvedValue({ advice: [makeAdvice()] });
    decideAdvice.mockRejectedValue(apiError(403, "产品风险等级高于你的风险承受等级"));
    const wrapper = await mountPage();

    await accept(wrapper);

    const failure = wrapper.get('[data-testid="advice-failure"]').text();
    expect(failure).toContain("产品风险等级高于你的风险承受等级");
    expect(wrapper.find('[data-testid="go-risk-assessment"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="advice-item"]')).toHaveLength(1);
  });

  it("renders the expiry reason when the acceptance arrives too late", async () => {
    listMyAdvice.mockResolvedValue({ advice: [makeAdvice()] });
    decideAdvice.mockRejectedValue(
      apiError(409, "该建议已过期，不能再接受，请客户经理重新发起"),
    );
    const wrapper = await mountPage();

    await accept(wrapper);

    expect(wrapper.get('[data-testid="advice-failure"]').text()).toContain("该建议已过期");
  });

  it("moves an accepted advice out of the pending group", async () => {
    listMyAdvice
      .mockResolvedValueOnce({ advice: [makeAdvice()] })
      .mockResolvedValueOnce({
        advice: [makeAdvice({ status: "已接受", decision: "接受", decided_at: "2026-09-22T10:00:00" })],
      });
    decideAdvice.mockResolvedValue(makeAdvice({ status: "已接受" }));
    const wrapper = await mountPage();

    await accept(wrapper);

    expect(decideAdvice).toHaveBeenCalledWith(1, "接受");
    expect(wrapper.find('[data-testid="advice-pending"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="advice-accepted"]').text()).toContain("已接受");
  });

  it("records a rejection without touching the balance", async () => {
    listMyAdvice.mockResolvedValue({ advice: [makeAdvice()] });
    decideAdvice.mockResolvedValue(makeAdvice({ status: "已拒绝", decision: "拒绝" }));
    const wrapper = await mountPage();

    await accept(wrapper, "reject-advice");

    expect(decideAdvice).toHaveBeenCalledWith(1, "拒绝");
  });
});
