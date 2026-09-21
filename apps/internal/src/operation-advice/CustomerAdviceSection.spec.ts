// 客户经理的发起入口与进度表：选客户 → 选方向 → 选产品 → 填金额 / 份额 → 发起 → 看进度。
// 这一侧**没有放行 / 驳回**：发起与放行是两件事（CONTEXT「客户经理」）。
import ElementPlus, { ElSelect } from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { apiError, stubApiFetch } from "../testing";
import CustomerAdviceSection from "./CustomerAdviceSection.vue";
import type { AdviceOption, OperationAdviceProgress } from "./types";

const CUSTOMERS = [
  {
    id: 9,
    username: "wangc1",
    real_name: "王小明",
    customer_level: "金卡",
    risk_level: "C3",
    manager_id: 4,
    status: "正常",
    opened_at: "2024-01-01T10:00:00",
  },
  {
    id: 10,
    username: "lisic2",
    real_name: "李小红",
    customer_level: "普通",
    risk_level: null,
    manager_id: 4,
    status: "正常",
    opened_at: "2024-02-01T10:00:00",
  },
];

const PROGRESS: OperationAdviceProgress[] = [
  {
    id: 21,
    product_code: "F000001",
    product_name: "稳健增利一号",
    direction: "申购",
    amount: "200000.00",
    reason: "客户现金持仓偏高。",
    review_status: "已放行",
    customer_status: "待客户决定",
    generated_at: "2026-09-18T09:00:00",
  },
  {
    id: 22,
    product_code: "F000002",
    product_name: "均衡配置二号",
    direction: "申购",
    amount: "50000.00",
    reason: "期限与流动性安排一致。",
    review_status: "待审",
    customer_status: null,
    generated_at: "2026-09-19T09:00:00",
  },
];

// 申购方向的可选项：一只买得起、一只买不起。买不起的那只仍然出现（禁用），不藏掉。
const PURCHASE_OPTIONS: AdviceOption[] = [
  {
    product_code: "F000001",
    product_name: "稳健增利一号",
    product_type: "混合型",
    risk_level: "R3",
    term_days: 365,
    min_amount: "1000.00",
    max_amount: "500000.00",
    affordable: true,
  },
  {
    product_code: "F000005",
    product_name: "进取成长五号",
    product_type: "股票型",
    risk_level: "R5",
    term_days: 720,
    min_amount: "5000.00",
    max_amount: "0.00",
    affordable: false,
  },
];

const REDEMPTION_OPTION: AdviceOption = {
  product_code: "F000003",
  product_name: "稳健增利三号",
  product_type: "混合型",
  risk_level: "R3",
  term_days: 180,
  min_amount: "1000.00",
  max_shares: "1200.0000",
  affordable: true,
};

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;
let progress: OperationAdviceProgress[] = PROGRESS;
// 读进度失败时替换成整个响应（非 200 由 http 客户端拆成 ApiError）。
let progressFailure: unknown = null;
let startResponse: unknown = { id: 23 };
// 可选项按方向分开放：切换方向要重取，mock 按 URL 里的 direction 返回对应一份。
let optionsByDirection: Record<string, { direction: string; products: AdviceOption[] }>;

async function mountSection(): Promise<VueWrapper> {
  stubApiFetch((url, init) => {
    if (url.includes("/operation-advice-options")) {
      const direction = url.includes("direction=")
        ? decodeURIComponent(url.split("direction=")[1])
        : "申购";
      return optionsByDirection[direction] ?? { direction, products: [] };
    }
    if (url.includes("/operation-advice") && init?.method === "POST") return startResponse;
    if (url.includes("/operation-advice")) return progressFailure ?? { advice: progress };
    return undefined;
  });

  pinia = createPinia();
  setActivePinia(pinia);

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", name: "landing", component: { template: "<div />" } },
      {
        path: "/advisory/operation-advice/:adviceId",
        name: "operation-advice-review",
        component: { template: "<div />" },
      },
    ],
  });
  await router.push("/");
  await router.isReady();

  wrapper = mount(CustomerAdviceSection, {
    props: { customers: CUSTOMERS },
    global: { plugins: [pinia, ElementPlus, router] },
  });
  await flushPromises();
  return wrapper;
}

async function selectCustomer(page: VueWrapper, customerId: number): Promise<void> {
  await page.findAllComponents(ElSelect)[0].setValue(customerId);
  await flushPromises();
}

async function selectProduct(page: VueWrapper, productCode: string): Promise<void> {
  await page.findAllComponents(ElSelect)[2].setValue(productCode);
  await flushPromises();
}

async function fillQuantity(page: VueWrapper, value: string): Promise<void> {
  await page.get('[data-testid="advice-quantity-input"]').setValue(value);
  await flushPromises();
}

/** 产品下拉（第三只 ElSelect）后端注册的可选项：label / value / disabled。 */
function productOptionsOf(page: VueWrapper): Array<{ value: string; label: string; disabled: boolean }> {
  const vm = page.findAllComponents(ElSelect)[2].vm as unknown as {
    optionsArray: Array<{ value: string; label: string; disabled: boolean }>;
  };
  return vm.optionsArray;
}

beforeEach(() => {
  localStorage.clear();
  progress = PROGRESS;
  progressFailure = null;
  startResponse = { id: 23 };
  optionsByDirection = {
    申购: { direction: "申购", products: PURCHASE_OPTIONS },
    赎回: { direction: "赎回", products: [] },
  };
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("客户经理的操作建议入口", () => {
  it("还没选客户时不渲染进度表，只有一句说明", async () => {
    const page = await mountSection();

    expect(page.find('[data-testid="advice-progress-table"]').exists()).toBe(false);
    expect(page.get('[data-testid="advice-progress-hint"]').text()).toContain("选择一位客户");
  });

  it("选中客户后渲染他名下已发起的建议与两列进度", async () => {
    const page = await mountSection();
    await selectCustomer(page, 9);

    const rows = page.get('[data-testid="advice-progress-table"]').findAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0].text()).toContain("稳健增利一号");
    expect(rows[0].text()).toContain("200,000.00");
    // 已放行的那条有客户决定，未放行的那条没有——不是「待客户决定」，是空。
    expect(rows[0].text()).toContain("已放行");
    expect(rows[0].text()).toContain("待客户决定");
    expect(rows[1].text()).toContain("待审");
    expect(rows[1].text()).toContain("—");
  });

  it("选中客户后加载可选项，每项显示五要素", async () => {
    const page = await mountSection();
    await selectCustomer(page, 9);

    const options = productOptionsOf(page);
    expect(options).toHaveLength(2);

    const first = options[0];
    expect(first.value).toBe("F000001");
    expect(first.label).toContain("稳健增利一号");
    expect(first.label).toContain("F000001");
    expect(first.label).toContain("R3");
    expect(first.label).toContain("365 天");
    expect(first.label).toContain("1000.00");
  });

  it("买不起的选项禁用并注明原因", async () => {
    const page = await mountSection();
    await selectCustomer(page, 9);

    const options = productOptionsOf(page);
    const unaffordable = options.find((option) => option.value === "F000005");
    expect(unaffordable).toBeDefined();
    expect(unaffordable?.disabled).toBe(true);
    expect(unaffordable?.label).toContain("可用余额不足");
  });

  it("候选池为空时渲染「没有合规产品可选」，不留空白", async () => {
    optionsByDirection["申购"] = { direction: "申购", products: [] };
    const page = await mountSection();
    await selectCustomer(page, 9);

    expect(page.get('[data-testid="advice-options-empty"]').text()).toContain(
      "该客户当前没有合规产品可选",
    );
    // 没有可选项，产品与金额两个字段都不渲染（不留空白）。
    expect(page.findAllComponents(ElSelect)).toHaveLength(2);
  });

  it("全部买不起时渲染「可用余额不足」文案，不留空白", async () => {
    optionsByDirection["申购"] = {
      direction: "申购",
      products: [
        {
          product_code: "F000005",
          product_name: "进取成长五号",
          product_type: "股票型",
          risk_level: "R5",
          term_days: 720,
          min_amount: "5000.00",
          max_amount: "0.00",
          affordable: false,
        },
      ],
    };
    const page = await mountSection();
    await selectCustomer(page, 9);

    expect(page.get('[data-testid="advice-options-empty"]').text()).toContain(
      "可用余额不足以申购候选池内的任何产品",
    );
    expect(page.findAllComponents(ElSelect)).toHaveLength(2);
  });

  it("切换方向后重新取可选项", async () => {
    const page = await mountSection();
    await selectCustomer(page, 9);
    expect(productOptionsOf(page)).toHaveLength(2);

    optionsByDirection["赎回"] = { direction: "赎回", products: [REDEMPTION_OPTION] };
    await page.findAllComponents(ElSelect)[1].setValue("赎回");
    await flushPromises();

    const redemptionOptions = productOptionsOf(page);
    expect(redemptionOptions).toHaveLength(1);
    expect(redemptionOptions[0].value).toBe("F000003");
  });

  it("发起建议带上产品与金额（申购），成功后重新拉一次进度", async () => {
    const page = await mountSection();
    await selectCustomer(page, 9);
    await selectProduct(page, "F000001");
    await fillQuantity(page, "1000");
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockClear();

    await page.get('[data-testid="start-advice"]').trigger("click");
    await flushPromises();

    const startCall = fetchMock.mock.calls.find(
      (call) => (call[1] as RequestInit)?.method === "POST",
    );
    expect(JSON.parse(String((startCall?.[1] as RequestInit).body))).toEqual({
      direction: "申购",
      product_code: "F000001",
      amount: "1000",
    });
    // 发起之后以服务端为准重新读一次进度。
    const reloads = fetchMock.mock.calls.filter((call) =>
      String(call[0]).includes("/operation-advice"),
    );
    expect(reloads.length).toBeGreaterThanOrEqual(2);
  });

  it("赎回方向提交带上份额（shares）", async () => {
    optionsByDirection["赎回"] = { direction: "赎回", products: [REDEMPTION_OPTION] };
    const page = await mountSection();
    await selectCustomer(page, 9);
    await page.findAllComponents(ElSelect)[1].setValue("赎回");
    await flushPromises();
    await selectProduct(page, "F000003");
    await fillQuantity(page, "600");
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockClear();

    await page.get('[data-testid="start-advice"]').trigger("click");
    await flushPromises();

    const startCall = fetchMock.mock.calls.find(
      (call) => (call[1] as RequestInit)?.method === "POST",
    );
    expect(JSON.parse(String((startCall?.[1] as RequestInit).body))).toEqual({
      direction: "赎回",
      product_code: "F000003",
      shares: "600",
    });
  });

  it("未选客户时发起按钮点不动", async () => {
    const page = await mountSection();

    expect(page.get('[data-testid="start-advice"]').attributes("disabled")).toBeDefined();
  });

  it("未选产品或未填金额时提交被拦", async () => {
    const page = await mountSection();
    await selectCustomer(page, 9);

    // 还没选产品：按钮禁用。
    expect(page.get('[data-testid="start-advice"]').attributes("disabled")).toBeDefined();

    await selectProduct(page, "F000001");
    // 选了产品但没填金额：按钮仍禁用。
    expect(page.get('[data-testid="start-advice"]').attributes("disabled")).toBeDefined();

    await fillQuantity(page, "1000");
    // 都齐了：按钮可用。
    expect(page.get('[data-testid="start-advice"]').attributes("disabled")).toBeUndefined();
  });

  it("发起失败时渲染后端给的原因", async () => {
    startResponse = apiError(400, "该客户不在你的名下，无权发起建议");
    const page = await mountSection();
    await selectCustomer(page, 9);
    await selectProduct(page, "F000001");
    await fillQuantity(page, "1000");

    await page.get('[data-testid="start-advice"]').trigger("click");
    await flushPromises();

    expect(page.get('[data-testid="start-advice-error"]').text()).toContain("不在你的名下");
  });

  it("点「查看」打开那条建议的审核页", async () => {
    const page = await mountSection();
    await selectCustomer(page, 9);

    await page.findAll('[data-testid="open-advice"]')[0].trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("operation-advice-review");
    expect(router.currentRoute.value.params.adviceId).toBe("21");
  });

  it("读不到进度时说读不到，不说成「还没有」", async () => {
    progressFailure = apiError(500, "服务内部错误");
    const page = await mountSection();
    await selectCustomer(page, 9);

    expect(page.get('[data-testid="advice-progress-error"]').text()).toContain("服务内部错误");
    expect(page.find('[data-testid="advice-progress-empty"]').exists()).toBe(false);
  });

  it("成功读到空时给空状态", async () => {
    progress = [];
    const page = await mountSection();
    await selectCustomer(page, 9);

    expect(page.get('[data-testid="advice-progress-empty"]').text()).toContain("还没有为他发起");
  });
});
