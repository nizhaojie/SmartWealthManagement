import ElementPlus from "element-plus";
import { ApiError } from "@wealth/shared";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAssets, getHoldingLookThrough, listTransactions } from "./api";
import type {
  CustomerAssets,
  Holding,
  LookThrough,
  LookThroughNode,
  TransactionRecord,
} from "./types";

// jsdom 里元素尺寸恒为 0，ECharts 拿不到画布尺寸就没有可布局的文字。
// 给一个稳定的尺寸，让「类别顺序」这类断言能在渲染结果上验。
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 480 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 260 });

vi.mock("./api", () => ({
  getAssets: vi.fn(),
  getHoldingLookThrough: vi.fn(),
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

function makeNode(overrides: Partial<LookThroughNode> = {}): LookThroughNode {
  return {
    kind: "asset",
    code: "CASH-0001",
    name: "同业存单",
    depth: 3,
    share: "0.030000",
    market_value: "3240.00",
    asset_category: "现金",
    children: [],
    ...overrides,
  };
}

// 与后端种子数据同形：F000003 直接持有两只基金，其中 F000002 自己还有一层底层资产。
function makeLookThrough(): LookThrough {
  return {
    product_code: "F000003",
    product_name: "天璇混合基金",
    market_value: "108000.00",
    root: {
      kind: "product",
      code: "F000003",
      name: "天璇混合基金",
      depth: 1,
      share: "1.000000",
      market_value: "108000.00",
      asset_category: null,
      children: [
        {
          kind: "product",
          code: "F000002",
          name: "天玑债券基金",
          depth: 2,
          share: "0.300000",
          market_value: "32400.00",
          asset_category: null,
          children: [
            makeNode({ code: "BOND-0001", name: "22 国债 05", share: "0.135000", market_value: "14580.00", asset_category: "债券" }),
            makeNode({ code: "BOND-0002", name: "23 国开债 10", share: "0.090000", market_value: "9720.00", asset_category: "债券" }),
            makeNode({ code: "BOND-0003", name: "中铁建公司债", share: "0.045000", market_value: "4860.00", asset_category: "债券" }),
            makeNode({ code: "CASH-0001", name: "同业存单", share: "0.030000", market_value: "3240.00", asset_category: "现金" }),
          ],
        },
        {
          kind: "product",
          code: "F000001",
          name: "天枢货币基金",
          depth: 2,
          share: "0.100000",
          market_value: "10800.00",
          asset_category: null,
          children: [
            makeNode({ code: "CASH-0001", name: "同业存单", share: "0.060000", market_value: "6480.00" }),
            makeNode({ code: "CASH-0002", name: "7 天通知存款", share: "0.040000", market_value: "4320.00" }),
          ],
        },
        makeNode({ code: "EQTY-0001", name: "沪深 300 成份股组合", depth: 2, share: "0.400000", market_value: "43200.00", asset_category: "股票" }),
        makeNode({ code: "BOND-0001", name: "22 国债 05", depth: 2, share: "0.200000", market_value: "21600.00", asset_category: "债券" }),
      ],
    },
    underlying_assets: [
      { asset_code: "EQTY-0001", asset_name: "沪深 300 成份股组合", asset_category: "股票", market_value: "43200.00", share: "0.400000", path_count: 1 },
      { asset_code: "BOND-0001", asset_name: "22 国债 05", asset_category: "债券", market_value: "36180.00", share: "0.335000", path_count: 2 },
      { asset_code: "BOND-0002", asset_name: "23 国开债 10", asset_category: "债券", market_value: "9720.00", share: "0.090000", path_count: 1 },
      { asset_code: "CASH-0001", asset_name: "同业存单", asset_category: "现金", market_value: "9720.00", share: "0.090000", path_count: 2 },
      { asset_code: "BOND-0003", asset_name: "中铁建公司债", asset_category: "债券", market_value: "4860.00", share: "0.045000", path_count: 1 },
      { asset_code: "CASH-0002", asset_name: "7 天通知存款", asset_category: "现金", market_value: "4320.00", share: "0.040000", path_count: 1 },
    ],
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

function entryOf(wrapper: PageWrapper, productCode: string) {
  return wrapper.get(
    `[data-testid="look-through-entry"][data-product-code="${productCode}"]`,
  );
}

function toggleNode(wrapper: PageWrapper, code: string) {
  return wrapper.get(`[data-testid="look-through-toggle"][data-code="${code}"]`).trigger("click");
}

function visibleNodeCodes(wrapper: PageWrapper): string[] {
  return wrapper
    .findAll('[data-testid="look-through-node"]')
    .map((node) => node.attributes("data-code") ?? "");
}

describe("AssetsPage", () => {
  beforeEach(() => {
    vi.mocked(getAssets).mockReset();
    vi.mocked(getHoldingLookThrough).mockReset();
    vi.mocked(listTransactions).mockReset();
    vi.mocked(getAssets).mockResolvedValue(makeAssets());
    vi.mocked(getHoldingLookThrough).mockResolvedValue(makeLookThrough());
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

  // 红涨绿跌（中国金融惯例）：页面只按符号挂 up/down 类，颜色经 03 号令牌给出。
  it("marks profit numbers by sign with the up/down classes", async () => {
    vi.mocked(getAssets).mockResolvedValue(
      makeAssets({
        holding_count: 2,
        holdings: [
          makeHolding({ profit_loss: "420.00", profit_ratio: "2.1000" }),
          makeHolding({
            product_code: "F000002",
            profit_loss: "-300.00",
            profit_ratio: "-1.5000",
          }),
        ],
      }),
    );
    const wrapper = await mountPage();

    const rows = wrapper.findAll('[data-testid="holdings-table"] tbody tr');
    // 第 6、7 列分别是盈亏（元）与盈亏比例（%）。
    const gainCells = rows[0].findAll("td");
    const lossCells = rows[1].findAll("td");
    expect(gainCells[5].classes()).toContain("profit-up");
    expect(gainCells[6].classes()).toContain("profit-up");
    expect(lossCells[5].classes()).toContain("profit-down");
    expect(lossCells[6].classes()).toContain("profit-down");
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

  it("opens a holding into its underlying assets one level at a time", async () => {
    vi.mocked(getAssets).mockResolvedValue(
      makeAssets({
        holding_count: 1,
        total_market_value: "108000.00",
        holdings: [
          makeHolding({
            product_code: "F000003",
            product_name: "天璇混合基金",
            product_type: "混合基金",
            product_risk_level: "R3",
            market_value: "108000.00",
          }),
        ],
      }),
    );
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="look-through-panel"]').exists()).toBe(false);

    await wrapper.get('[data-testid="look-through-entry"]').trigger("click");
    await flushPromises();

    expect(getHoldingLookThrough).toHaveBeenCalledWith("F000003");
    // 展开持仓后先看到直接持有的下一层，更深的层级还收着。
    expect(visibleNodeCodes(wrapper)).toEqual([
      "F000003",
      "F000002",
      "F000001",
      "EQTY-0001",
      "BOND-0001",
    ]);

    await toggleNode(wrapper, "F000002");
    expect(visibleNodeCodes(wrapper)).toEqual([
      "F000003",
      "F000002",
      "BOND-0001",
      "BOND-0002",
      "BOND-0003",
      "CASH-0001",
      "F000001",
      "EQTY-0001",
      "BOND-0001",
    ]);

    // 第 3 层的占比是沿路径乘出来的（30% × 45%），不是它相对 F000002 的 45%，
    // 否则同一行里占比与市值会各说各话。
    const deepest = wrapper
      .findAll('[data-testid="look-through-node"]')
      .find((node) => node.attributes("data-code") === "BOND-0001" && node.text().includes("第 3 层"));
    expect(deepest?.text()).toContain("13.50%");
    expect(deepest?.text()).toContain("14580.00");

    await toggleNode(wrapper, "F000002");
    expect(visibleNodeCodes(wrapper)).toEqual([
      "F000003",
      "F000002",
      "F000001",
      "EQTY-0001",
      "BOND-0001",
    ]);

    await wrapper.get('[data-testid="look-through-entry"]').trigger("click");
    expect(wrapper.find('[data-testid="look-through-panel"]').exists()).toBe(false);
  });

  it("merges the paths that end on the same underlying asset into one row", async () => {
    const wrapper = await mountPage();
    await wrapper.get('[data-testid="look-through-entry"]').trigger("click");
    await flushPromises();

    const rows = wrapper.findAll('[data-testid="look-through-asset"]');
    expect(rows.map((row) => row.attributes("data-asset-code"))).toEqual([
      "EQTY-0001",
      "BOND-0001",
      "BOND-0002",
      "CASH-0001",
      "BOND-0003",
      "CASH-0002",
    ]);

    const bond = rows.find((row) => row.attributes("data-asset-code") === "BOND-0001");
    expect(bond?.text()).toContain("36180.00");
    expect(bond?.text()).toContain("2 条");

    // 合并是相加，不是给每条路径各留一份市值。
    const merged = rows.reduce((sum, row) => sum + Number(row.findAll("td")[2].text()), 0);
    expect(merged).toBeCloseTo(108000, 2);
  });

  it("loads each holding's look-through on demand and keeps one open at a time", async () => {
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
          }),
        ],
      }),
    );
    const wrapper = await mountPage();

    await entryOf(wrapper, "F000001").trigger("click");
    await flushPromises();
    expect(getHoldingLookThrough).toHaveBeenLastCalledWith("F000001");
    expect(wrapper.findAll('[data-testid="look-through-panel"]')).toHaveLength(1);

    await entryOf(wrapper, "F000002").trigger("click");
    await flushPromises();
    expect(getHoldingLookThrough).toHaveBeenLastCalledWith("F000002");
    expect(wrapper.findAll('[data-testid="look-through-panel"]')).toHaveLength(1);

    await entryOf(wrapper, "F000001").trigger("click");
    await flushPromises();
    expect(getHoldingLookThrough).toHaveBeenCalledTimes(2);
  });

  it("reports a cyclic holding relation instead of leaving the panel blank", async () => {
    vi.mocked(getHoldingLookThrough).mockRejectedValue(
      new ApiError({
        code: 1003,
        message: "持仓穿透发现成环的底层持有关系：F900001 > F900002 > F900001，展开已停止。",
        data: null,
        trace_id: "",
      }),
    );
    const wrapper = await mountPage();

    await wrapper.get('[data-testid="look-through-entry"]').trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="look-through-panel"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="look-through-error"]').text()).toContain("成环");
  });
});
