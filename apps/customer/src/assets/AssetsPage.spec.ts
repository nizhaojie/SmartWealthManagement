import ElementPlus from "element-plus";
import { ApiError } from "@wealth/shared";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAssets, listTransactions } from "./api";
import type { CustomerAssets, Holding, TransactionRecord } from "./types";

// jsdom 里元素尺寸恒为 0，ECharts 拿不到画布尺寸就没有可布局的文字。
// 给一个稳定的尺寸，让「类别顺序」这类断言能在渲染结果上验。
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 480 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 260 });

vi.mock("./api", () => ({
  getAssets: vi.fn(),
  listTransactions: vi.fn(),
}));

import AssetsPage from "./AssetsPage.vue";

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

function makeAssets(overrides: Partial<CustomerAssets> = {}): CustomerAssets {
  return {
    risk_level: "C1",
    risk_level_valid_until: "2027-03-15",
    total_market_value: "20420.00",
    holding_count: 1,
    holdings: [makeHolding()],
    ...overrides,
  };
}

function makeTransaction(overrides: Partial<TransactionRecord> = {}): TransactionRecord {
  return {
    transaction_no: "TX202204100001",
    transaction_type: "申购",
    product_code: "F000001",
    product_name: "天枢货币基金",
    amount: "20000.00",
    shares: "20000.0000",
    nav: "1.000000",
    fee: "0.00",
    status: "已确认",
    traded_at: "2022-04-10T10:30:00",
    ...overrides,
  };
}

async function mountPage() {
  const wrapper = mount(AssetsPage, {
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  });
  await flushPromises();
  return wrapper;
}

const ALLOCATION_CHART_TITLE = "实际配置";
const RISK_LEVEL_CHART_TITLE = "持仓按产品风险等级的分布";

type PageWrapper = Awaited<ReturnType<typeof mountPage>>;

function chartFrameOf(wrapper: PageWrapper, title: string) {
  const frame = wrapper
    .findAll('[data-testid="chart-frame"]')
    .find((node) => node.find("figcaption").text() === title);
  if (frame === undefined) throw new Error(`资产页上没有标题为「${title}」的图表`);
  return frame;
}

describe("AssetsPage", () => {
  beforeEach(() => {
    vi.mocked(getAssets).mockReset();
    vi.mocked(listTransactions).mockReset();
    vi.mocked(getAssets).mockResolvedValue(makeAssets());
    vi.mocked(listTransactions).mockResolvedValue({ transactions: [makeTransaction()] });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows total market value, holding count and the risk tolerance conclusion", async () => {
    vi.mocked(getAssets).mockResolvedValue(
      makeAssets({ total_market_value: "128420.00", holding_count: 3, risk_level: "C3" }),
    );
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="total-market-value"]').text()).toBe("128420.00");
    expect(wrapper.get('[data-testid="holding-count"]').text()).toBe("3");
    const riskLevel = wrapper.get('[data-testid="risk-level"]').text();
    expect(riskLevel).toContain("C3");
    expect(riskLevel).toContain("平衡型");
  });

  it("lists every holding with its product, shares, cost, market value and profit", async () => {
    vi.mocked(getAssets).mockResolvedValue(
      makeAssets({
        holding_count: 2,
        holdings: [
          makeHolding(),
          makeHolding({
            product_code: "F000002",
            product_name: "天玑债券基金",
            product_type: "债券基金",
            product_risk_level: "R2",
            shares: "41666.6667",
            cost_amount: "50000.00",
            market_value: "52000.00",
            profit_loss: "2000.00",
            profit_ratio: "4.0000",
          }),
        ],
      }),
    );
    const wrapper = await mountPage();

    const rows = wrapper.findAll('[data-testid="holdings-table"] tbody tr');
    expect(rows).toHaveLength(2);
    expect(rows[0].text()).toContain("天枢货币基金");
    expect(rows[0].text()).toContain("20000.0000");
    expect(rows[0].text()).toContain("20000.00");
    expect(rows[0].text()).toContain("20420.00");
    expect(rows[0].text()).toContain("420.00");
    expect(rows[1].text()).toContain("F000002");
  });

  it("renders a friendly empty state instead of an empty holdings table", async () => {
    vi.mocked(getAssets).mockResolvedValue(
      makeAssets({ total_market_value: "0.00", holding_count: 0, holdings: [] }),
    );
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="holdings-table"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="holding-count"]').text()).toBe("0");
    expect(wrapper.get('[data-testid="holdings-empty"]').text()).toContain("还没有持有");
  });

  it("filters transactions by date range and transaction type", async () => {
    vi.mocked(listTransactions).mockResolvedValue({
      transactions: [makeTransaction({ transaction_no: "TX202305060001", transaction_type: "赎回" })],
    });
    const wrapper = await mountPage();

    expect(listTransactions).toHaveBeenCalledWith({});

    await wrapper.get('input[name="start_date"]').setValue("2023-01-01");
    await wrapper.get('input[name="end_date"]').setValue("2023-12-31");
    await wrapper.get('select[name="transaction_type"]').setValue("赎回");
    await wrapper.get('button[name="apply-transaction-filters"]').trigger("click");
    await flushPromises();

    expect(listTransactions).toHaveBeenLastCalledWith({
      start_date: "2023-01-01",
      end_date: "2023-12-31",
      transaction_type: "赎回",
    });
    expect(wrapper.get('[data-testid="transactions-table"] tbody tr').text()).toContain(
      "TX202305060001",
    );
  });

  it("explains an empty transaction list rather than showing a bare table", async () => {
    vi.mocked(listTransactions).mockResolvedValue({ transactions: [] });
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="transactions-table"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="transactions-empty"]').text()).toContain("放宽");
  });

  it("says so instead of guessing when there is no risk tolerance conclusion yet", async () => {
    vi.mocked(getAssets).mockResolvedValue(
      makeAssets({ risk_level: null, risk_level_valid_until: null }),
    );
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="risk-level"]').text()).toBe("尚未测评");
    expect(wrapper.get('[data-testid="total-market-value"]').text()).toBe("20420.00");
  });

  it("draws both charts from the holdings", async () => {
    vi.mocked(getAssets).mockResolvedValue(
      makeAssets({
        holdings: [
          makeHolding({ product_type: "债券基金", product_risk_level: "R2", market_value: "90000.00" }),
          makeHolding({
            product_code: "F000004",
            product_type: "股票基金",
            product_risk_level: "R4",
            market_value: "80000.00",
          }),
        ],
      }),
    );
    const wrapper = await mountPage();

    expect(chartFrameOf(wrapper, ALLOCATION_CHART_TITLE).find('[data-testid="chart-canvas"]').exists()).toBe(true);
    expect(
      chartFrameOf(wrapper, RISK_LEVEL_CHART_TITLE).find('[data-testid="chart-canvas"]').exists(),
    ).toBe(true);
  });

  it("keeps the risk level categories in R1 to R5 order instead of sorting by size", async () => {
    vi.mocked(getAssets).mockResolvedValue(
      makeAssets({
        holdings: [
          makeHolding({ product_risk_level: "R4", market_value: "80000.00" }),
          makeHolding({
            product_code: "F000005",
            product_type: "股票基金",
            product_risk_level: "R5",
            market_value: "30000.00",
          }),
          makeHolding({
            product_code: "F000002",
            product_type: "债券基金",
            product_risk_level: "R2",
            market_value: "2000.00",
          }),
        ],
      }),
    );
    const wrapper = await mountPage();

    // 读的是图上类别标签的先后顺序，不涉及任何几何位置或像素。
    const labels = chartFrameOf(wrapper, RISK_LEVEL_CHART_TITLE)
      .findAll("svg text")
      .map((node) => node.text())
      .filter((text) => /^R[1-5]$/.test(text));

    expect(labels).toEqual(["R1", "R2", "R3", "R4", "R5"]);
  });

  it("leaves no blank chart area when there is nothing to plot", async () => {
    vi.mocked(getAssets).mockResolvedValue(
      makeAssets({ total_market_value: "0.00", holding_count: 0, holdings: [] }),
    );
    const wrapper = await mountPage();

    expect(wrapper.findAll('[data-testid="chart-empty"]')).toHaveLength(2);
    expect(wrapper.findAll('[data-testid="chart-canvas"]')).toHaveLength(0);
    expect(chartFrameOf(wrapper, ALLOCATION_CHART_TITLE).text()).toContain("还没有可以统计的持仓");
  });

  it("shows an explicit loading state for both charts", async () => {
    vi.mocked(getAssets).mockReturnValue(new Promise<CustomerAssets>(() => {}));
    const wrapper = await mountPage();

    expect(wrapper.findAll('[data-testid="chart-loading"]')).toHaveLength(2);
    expect(wrapper.findAll('[data-testid="chart-canvas"]')).toHaveLength(0);
  });

  it("surfaces a failure to load assets instead of leaving the page blank", async () => {
    vi.mocked(getAssets).mockRejectedValue(
      new ApiError({ code: 1002, message: "资产信息加载失败", data: null, trace_id: "" }),
    );
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="assets-error"]').text()).toContain("资产信息加载失败");
    expect(wrapper.find('[data-testid="asset-summary"]').exists()).toBe(false);
  });
});
