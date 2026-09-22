// 资产页：可用余额与持仓总市值并排，「去交易」入口通向独立的交易页。
// 流水已迁到交易页（spec「交易流水归位」），资产页不再渲染流水卡片。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

const { getAssets, getHoldingLookThrough } = vi.hoisted(() => ({
  getAssets: vi.fn(),
  getHoldingLookThrough: vi.fn(),
}));
const { getFundingAccount } = vi.hoisted(() => ({ getFundingAccount: vi.fn() }));

vi.mock("./api", () => ({ getAssets, getHoldingLookThrough }));
vi.mock("../funding/api", () => ({ getFundingAccount }));

import AssetsPage from "./AssetsPage.vue";

const Blank = { render: () => h("div") };

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

  it("no longer renders the transaction history card", async () => {
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="transactions-table"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="transactions-empty"]').exists()).toBe(false);
  });
});
