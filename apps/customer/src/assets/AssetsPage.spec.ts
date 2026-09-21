// 资产页的两处新增：可用余额 +「去交易」入口，以及合并流水里的三类记录。
// 流水那一条是本 slice 最容易漏的地方——`INNER JOIN fin_product` 一旦留着，
// 转账行会整行消失且不报错，所以这里专门盯「流水里有转账」。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import type { TransactionRecord } from "./types";

const { getAssets, listTransactions, getHoldingLookThrough } = vi.hoisted(() => ({
  getAssets: vi.fn(),
  listTransactions: vi.fn(),
  getHoldingLookThrough: vi.fn(),
}));
const { getFundingAccount } = vi.hoisted(() => ({ getFundingAccount: vi.fn() }));

vi.mock("./api", () => ({ getAssets, listTransactions, getHoldingLookThrough }));
vi.mock("../funding/api", () => ({ getFundingAccount }));

import AssetsPage from "./AssetsPage.vue";

const Blank = { render: () => h("div") };

function makeFlow(overrides: Partial<TransactionRecord> = {}): TransactionRecord {
  return {
    transaction_no: "TR20260921ABCDEF",
    transaction_type: "转账",
    product_code: null,
    product_name: null,
    amount: "500000.00",
    shares: null,
    nav: null,
    fee: null,
    status: "已确认",
    traded_at: "2026-09-21T09:00:00",
    payee_name: "张三",
    payee_account: "6222020200112233",
    ...overrides,
  };
}

let router: Router;
let activeWrapper: VueWrapper | null = null;

async function mountPage(): Promise<VueWrapper> {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/assets", name: "assets", component: Blank },
      { path: "/trading", name: "trading", component: Blank },
    ],
  });
  await router.push("/assets");
  await router.isReady();
  activeWrapper = mount(AssetsPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return activeWrapper;
}

describe("AssetsPage", () => {
  beforeEach(() => {
    getAssets.mockReset();
    listTransactions.mockReset();
    getHoldingLookThrough.mockReset();
    getFundingAccount.mockReset();

    getFundingAccount.mockResolvedValue({ available_balance: "100000.00" });
    getAssets.mockResolvedValue({
      risk_level: "C1",
      risk_level_valid_until: "2027-03-15",
      total_market_value: "20420.00",
      holding_count: 1,
      holdings: [],
    });
    listTransactions.mockResolvedValue({ transactions: [] });
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("shows the available balance next to the holdings and links to 交易", async () => {
    const wrapper = await mountPage();

    const summary = wrapper.get('[data-testid="asset-summary"]').text();
    expect(summary).toContain("可用余额（元）");
    expect(summary).toContain("100000.00");

    await wrapper.get('[data-testid="go-trading"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/trading");
  });

  it("renders 申购、赎回与转账 in the merged history, with the payee on the transfer row", async () => {
    listTransactions.mockResolvedValue({
      transactions: [
        makeFlow(),
        makeFlow({
          transaction_no: "TR20260920AAAAAA",
          transaction_type: "赎回",
          product_code: "F000001",
          product_name: "天枢货币基金",
          shares: "1000.0000",
          nav: "1.0000",
          fee: "1.00",
          payee_name: null,
          payee_account: null,
        }),
      ],
    });
    const wrapper = await mountPage();

    const transfer = wrapper.get('[data-transaction-type="转账"]');
    expect(transfer.text()).toContain("张三");
    expect(transfer.text()).toContain("6222020200112233");
    // 转账没有产品：这一格是「—」，不是空白，也不是某只产品的名字。
    expect(transfer.text()).toContain("—");
    expect(transfer.text()).not.toContain("天枢货币基金");

    const redemption = wrapper.get('[data-transaction-type="赎回"]');
    expect(redemption.text()).toContain("天枢货币基金");
    expect(redemption.text()).not.toContain("张三");
  });

  it("leaves an explanation instead of a blank history when there is no transaction", async () => {
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="transactions-empty"]').text()).toContain("没有符合条件的交易记录");
  });
});
