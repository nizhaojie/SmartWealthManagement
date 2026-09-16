import { ChartFrame } from "@wealth/shared";
import { flushPromises, mount } from "@vue/test-utils";
import { nextTick } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CustomerGraphView } from "./types";

// jsdom 里元素尺寸恒为 0，ECharts 拿不到画布尺寸就没有可布局的文字。
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 480 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 360 });

const { getCustomerGraph } = vi.hoisted(() => ({ getCustomerGraph: vi.fn() }));

vi.mock("./api", () => ({ getCustomerGraph }));

import CustomerGraphPanel from "./CustomerGraphPanel.vue";

function makeView(overrides: Partial<CustomerGraphView> = {}): CustomerGraphView {
  return {
    customer_id: 1,
    nodes: [
      {
        id: "customer:1",
        type: "customer",
        label: "客户甲",
        attrs: { customer_id: 1, real_name: "客户甲" },
        marked: false,
      },
      {
        id: "product:P1",
        type: "product",
        label: "产品甲",
        attrs: { product_code: "P1", product_name: "产品甲" },
        marked: false,
      },
      {
        id: "industry:I1",
        type: "industry",
        label: "行业甲",
        attrs: { industry: "行业甲", share: 0.5 },
        marked: true,
      },
    ],
    edges: [
      { source: "customer:1", target: "product:P1", type: "HOLDS" },
      { source: "product:P1", target: "industry:I1", type: "BELONGS_TO_INDUSTRY" },
    ],
    synced_at: "2024-01-02T03:04:05",
    ...overrides,
  };
}

async function mountPanel(view: CustomerGraphView = makeView()) {
  getCustomerGraph.mockResolvedValue(view);
  const wrapper = mount(CustomerGraphPanel, { props: { customerId: 1 } });
  await flushPromises();
  return wrapper;
}

describe("CustomerGraphPanel", () => {
  beforeEach(() => {
    getCustomerGraph.mockReset();
  });

  it("shows the chart-frame loading state while the graph request is in flight", async () => {
    let resolveRequest: (value: CustomerGraphView) => void = () => {};
    getCustomerGraph.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );
    const wrapper = mount(CustomerGraphPanel, { props: { customerId: 1 } });
    await nextTick();

    expect(wrapper.find('[data-testid="chart-loading"]').exists()).toBe(true);

    resolveRequest(makeView());
    await flushPromises();

    expect(wrapper.find('[data-testid="chart-loading"]').exists()).toBe(false);
  });

  it("renders the two-hop graph by default with the customer/product/industry labels", async () => {
    const wrapper = await mountPanel();

    const frame = wrapper.find('[data-testid="chart-frame"]');
    expect(frame.find('[data-testid="chart-canvas"]').exists()).toBe(true);

    const labels = frame.findAll("svg text").map((node) => node.text());
    expect(labels).toContain("客户甲");
    expect(labels).toContain("产品甲");
    expect(labels).toContain("行业甲");

    expect(getCustomerGraph).toHaveBeenCalledWith(1, { expandFundManager: false });
  });

  it("renders an empty state instead of a blank canvas when the graph has no edges", async () => {
    const wrapper = await mountPanel(makeView({ edges: [] }));

    const frame = wrapper.find('[data-testid="chart-frame"]');
    expect(frame.find('[data-testid="chart-empty"]').exists()).toBe(true);
    expect(frame.find('[data-testid="chart-canvas"]').exists()).toBe(false);
  });

  it("unchecking a relationship-type filter drops the edges of that type from the render", async () => {
    const wrapper = await mountPanel();

    await wrapper.get('[data-test="graph-filter-BELONGS_TO_INDUSTRY"]').setValue(false);
    await nextTick();

    const labels = wrapper
      .find('[data-testid="chart-frame"]')
      .findAll("svg text")
      .map((node) => node.text());
    expect(labels).toContain("客户甲");
    expect(labels).toContain("产品甲");
    expect(labels).not.toContain("行业甲");
  });

  it("shows the graph sync time, or a not-yet-synced label when absent", async () => {
    const synced = await mountPanel(makeView({ synced_at: "2024-01-02T03:04:05" }));
    expect(synced.get('[data-test="graph-synced-at"]').text()).toBe("图谱同步于 2024-01-02 03:04");

    const notSynced = await mountPanel(makeView({ synced_at: null }));
    expect(notSynced.get('[data-test="graph-synced-at"]').text()).toBe("图谱尚未同步");
  });

  it("expanding fund managers re-requests the graph with the expand flag", async () => {
    const wrapper = await mountPanel();
    getCustomerGraph.mockResolvedValue(
      makeView({
        nodes: [
          ...makeView().nodes,
          {
            id: "fund_manager:M1",
            type: "fund_manager",
            label: "经理甲",
            attrs: { name: "经理甲" },
            marked: false,
          },
        ],
        edges: [...makeView().edges, { source: "product:P1", target: "fund_manager:M1", type: "MANAGED_BY" }],
      }),
    );

    await wrapper.get('[data-test="graph-expand-fund-manager"]').trigger("click");
    await flushPromises();

    expect(getCustomerGraph).toHaveBeenLastCalledWith(1, { expandFundManager: true });
    const labels = wrapper
      .find('[data-testid="chart-frame"]')
      .findAll("svg text")
      .map((node) => node.text());
    expect(labels).toContain("经理甲");
  });

  it("clicking a node shows its attrs in a detail panel without navigating away", async () => {
    const wrapper = await mountPanel();

    await wrapper.findComponent(ChartFrame).vm.$emit("elementClick", {
      dataType: "node",
      data: { id: "product:P1" },
    });
    await nextTick();

    const detail = wrapper.get('[data-test="graph-node-detail"]');
    expect(detail.text()).toContain("产品甲");
    expect(detail.text()).toContain("P1");
  });
});
