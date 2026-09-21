// 「交易」页的受理失败：三类拒绝各自渲染受理侧原文，未测评那一条要能点到测评页。
// 受理结果（成交与余额刷新）与无持仓的空状态也在这里钉住。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ApiError } from "@wealth/shared";
import type { Holding, TransactionRecord } from "../assets/types";
import type { Product } from "../products/types";

const { purchase, redeem, transfer } = vi.hoisted(() => ({
  purchase: vi.fn(),
  redeem: vi.fn(),
  transfer: vi.fn(),
}));
const { getFundingAccount } = vi.hoisted(() => ({ getFundingAccount: vi.fn() }));
const { getAssets } = vi.hoisted(() => ({ getAssets: vi.fn() }));
const { listProducts } = vi.hoisted(() => ({ listProducts: vi.fn() }));

vi.mock("./api", () => ({ purchase, redeem, transfer }));
vi.mock("../funding/api", () => ({ getFundingAccount }));
vi.mock("../assets/api", () => ({ getAssets }));
vi.mock("../products/api", () => ({ listProducts }));

import TradingPage from "./TradingPage.vue";

const Blank = { render: () => h("div") };

function apiError(code: number, message: string): ApiError {
  return new ApiError({ code, message, data: null, trace_id: "t-1" });
}

function makeHolding(overrides: Partial<Holding> = {}): Holding {
  return {
    product_code: "F000001",
    product_name: "天枢货币基金",
    product_type: "货币基金",
    product_risk_level: "R1",
    shares: "20000.0000",
    cost_amount: "20000.00",
    market_value: "20420.00",
    profit_loss: "420.00",
    profit_ratio: "2.1000",
    ...overrides,
  };
}

function makeProduct(overrides: Partial<Product> = {}): Product {
  return {
    product_code: "F000001",
    product_name: "天枢货币基金",
    product_type: "货币基金",
    risk_level: "R1",
    expected_return: "2.1000",
    min_amount: "1000.00",
    term_days: 0,
    fund_manager: null,
    fee_rate: "0.1000",
    status: "在售",
    ...overrides,
  };
}

function makeTransaction(overrides: Partial<TransactionRecord> = {}): TransactionRecord {
  return {
    transaction_no: "TR20260921ABCDEF",
    transaction_type: "申购",
    product_code: "F000001",
    product_name: "天枢货币基金",
    amount: "5000.00",
    shares: "5000.0000",
    nav: "1.0000",
    fee: "5.00",
    status: "已确认",
    traded_at: "2026-09-21T09:00:00",
    payee_name: null,
    payee_account: null,
    ...overrides,
  };
}

let router: Router;
let activeWrapper: VueWrapper | null = null;

async function mountPage(): Promise<VueWrapper> {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/trading", name: "trading", component: Blank },
      { path: "/risk-assessment", name: "risk-assessment", component: Blank },
    ],
  });
  await router.push("/trading");
  await router.isReady();
  activeWrapper = mount(TradingPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return activeWrapper;
}

async function submit(wrapper: VueWrapper, testid: string): Promise<void> {
  await wrapper.get(`[data-testid="${testid}"]`).trigger("submit.prevent");
  await flushPromises();
}

describe("TradingPage", () => {
  beforeEach(() => {
    purchase.mockReset();
    redeem.mockReset();
    transfer.mockReset();
    getFundingAccount.mockReset();
    getAssets.mockReset();
    listProducts.mockReset();

    getFundingAccount.mockResolvedValue({ available_balance: "100000.00" });
    getAssets.mockResolvedValue({
      risk_level: "C1",
      risk_level_valid_until: "2027-03-15",
      total_market_value: "20420.00",
      holding_count: 1,
      holdings: [makeHolding()],
    });
    listProducts.mockResolvedValue({ products: [makeProduct()] });
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("renders the available balance and the three entries", async () => {
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="available-balance"]').text()).toContain("100000.00");
    expect(wrapper.find('button[name="submit-purchase"]').exists()).toBe(true);
    expect(wrapper.find('button[name="submit-redemption"]').exists()).toBe(true);
    expect(wrapper.find('button[name="submit-transfer"]').exists()).toBe(true);
  });

  it("renders the acceptance message when the balance is short", async () => {
    purchase.mockRejectedValue(apiError(400, "可用余额不足，还差 200.00 元"));
    const wrapper = await mountPage();

    await submit(wrapper, "purchase-form");

    expect(wrapper.get('[data-testid="purchase-failure"]').text()).toContain(
      "可用余额不足，还差 200.00 元",
    );
    // 余额不足不是客户自己能解决的问题，因此不给测评入口。
    expect(wrapper.find('[data-testid="go-risk-assessment"]').exists()).toBe(false);
  });

  it("renders the acceptance message when the product is above the customer's grade", async () => {
    purchase.mockRejectedValue(apiError(403, "产品风险等级高于你的风险承受等级"));
    const wrapper = await mountPage();

    await submit(wrapper, "purchase-form");

    const failure = wrapper.get('[data-testid="purchase-failure"]').text();
    expect(failure).toContain("产品风险等级高于你的风险承受等级");
    expect(failure).not.toContain("请先完成风险测评");
  });

  it("links to 风险测评 when the customer never completed an assessment", async () => {
    purchase.mockRejectedValue(apiError(403, "请先完成风险测评"));
    const wrapper = await mountPage();

    await submit(wrapper, "purchase-form");

    expect(wrapper.get('[data-testid="purchase-failure"]').text()).toContain("请先完成风险测评");

    await wrapper.get('[data-testid="go-risk-assessment"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/risk-assessment");
  });

  it("renders the same acceptance message on 转账", async () => {
    transfer.mockRejectedValue(apiError(400, "可用余额不足，还差 1200.00 元"));
    const wrapper = await mountPage();

    await submit(wrapper, "transfer-form");

    expect(wrapper.get('[data-testid="transfer-failure"]').text()).toContain(
      "可用余额不足，还差 1200.00 元",
    );
  });

  it("leaves no blank where there is no holding to redeem", async () => {
    getAssets.mockResolvedValue({
      risk_level: null,
      risk_level_valid_until: null,
      total_market_value: "0.00",
      holding_count: 0,
      holdings: [],
    });
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="redemption-form"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="redemption-empty"]').text()).toContain("没有可赎回的持仓");
  });

  // 「拉取失败」不是「你没有持仓」：把接口故障说成没有可赎回的东西，客户会去查一个
  // 并不存在的问题，而且不会有人知道接口其实挂了。
  it("does not present a failed holdings load as an empty portfolio", async () => {
    getAssets.mockRejectedValue(apiError(500, "服务内部错误"));
    listProducts.mockRejectedValue(apiError(500, "服务内部错误"));
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="holdings-error"]').text()).toContain("服务内部错误");
    expect(wrapper.find('[data-testid="redemption-empty"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="products-error"]').text()).toContain("服务内部错误");
    expect(wrapper.find('[data-testid="purchase-empty"]').exists()).toBe(false);
  });

  it("takes the balance from the acceptance result after a 申购", async () => {
    purchase.mockResolvedValue({
      transaction: makeTransaction(),
      available_balance: "94995.00",
    });
    const wrapper = await mountPage();

    await submit(wrapper, "purchase-form");

    expect(wrapper.get('[data-testid="purchase-done"]').text()).toContain("TR20260921ABCDEF");
    expect(wrapper.get('[data-testid="available-balance"]').text()).toContain("94995.00");
    expect(wrapper.find('[data-testid="purchase-failure"]').exists()).toBe(false);
  });
});
