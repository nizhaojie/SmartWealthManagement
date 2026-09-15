import ElementPlus from "element-plus";
import { ApiError } from "@wealth/shared";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AdvisoryRequest } from "../advisory/types";
import type { Product } from "./types";

const { listProducts, getProduct } = vi.hoisted(() => ({
  listProducts: vi.fn(),
  getProduct: vi.fn(),
}));

const { listAdvisoryRequests, submitAdvisoryRequest } = vi.hoisted(() => ({
  listAdvisoryRequests: vi.fn(),
  submitAdvisoryRequest: vi.fn(),
}));

vi.mock("./api", () => ({ listProducts, getProduct }));
vi.mock("../advisory/api", () => ({ listAdvisoryRequests, submitAdvisoryRequest }));

import ProductScreeningPage from "./ProductScreeningPage.vue";

const DISCLAIMER = "这是符合条件的产品清单，不是推荐";

function makeProduct(overrides: Partial<Product> = {}): Product {
  return {
    product_code: "F000001",
    product_name: "天枢货币基金",
    product_type: "货币基金",
    risk_level: "R1",
    expected_return: "2.1000",
    min_amount: "1000.00",
    term_days: 0,
    fund_manager: "吴宁",
    fee_rate: "0.2500",
    status: "在售",
    ...overrides,
  };
}

function productsOfCount(count: number): Product[] {
  return Array.from({ length: count }, (_, index) => {
    const n = String(index + 1).padStart(6, "0");
    return makeProduct({
      product_code: `F${n}`,
      product_name: `示例产品${index + 1}`,
      expected_return: String((index + 1) * 2),
    });
  });
}

function makeRequest(overrides: Partial<AdvisoryRequest> = {}): AdvisoryRequest {
  return {
    id: 1,
    request_no: "AR20260915A1B2C3",
    customer_id: 7,
    status: "待处理",
    filters: { product_type: "债券基金" },
    submitted_at: "2026-09-15T08:30:00",
    ...overrides,
  };
}

async function mountPage() {
  const wrapper = mount(ProductScreeningPage, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return wrapper;
}

describe("ProductScreeningPage", () => {
  beforeEach(() => {
    listProducts.mockReset();
    getProduct.mockReset();
    listAdvisoryRequests.mockReset();
    submitAdvisoryRequest.mockReset();
    listProducts.mockResolvedValue({ products: [makeProduct()] });
    listAdvisoryRequests.mockResolvedValue({ requests: [] });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not render sortable table headers, so clicking 业绩基准 cannot reorder rows", async () => {
    listProducts.mockResolvedValue({
      products: [
        makeProduct({ product_code: "F000001", expected_return: "2.1000" }),
        makeProduct({
          product_code: "F000002",
          product_name: "天玑债券基金",
          product_type: "债券基金",
          risk_level: "R2",
          expected_return: "18.0000",
        }),
      ],
    });
    const wrapper = await mountPage();

    const headers = wrapper.findAll("table thead th");
    expect(headers.length).toBeGreaterThan(0);
    expect(wrapper.findAll("th[aria-sort]")).toHaveLength(0);
    expect(wrapper.findAll(".caret-wrapper")).toHaveLength(0);
    for (const header of headers) {
      expect(header.find("button").exists()).toBe(false);
    }

    const codesBefore = wrapper.findAll("tbody tr").map((row) => row.text());
    const benchmarkHeader = headers.find((header) => header.text().includes("业绩基准"));
    expect(benchmarkHeader).toBeDefined();
    await benchmarkHeader!.trigger("click");
    await flushPromises();

    expect(wrapper.findAll("tbody tr").map((row) => row.text())).toEqual(codesBefore);
    expect(wrapper.findAll("tbody tr")[0].text()).toContain("F000001");
  });

  it.each([1, 2, 20])("keeps the not-a-recommendation notice when there are %s products", async (count) => {
    listProducts.mockResolvedValue({ products: productsOfCount(count) });
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="not-recommendation"]').text()).toBe(DISCLAIMER);
    expect(wrapper.findAll("tbody tr")).toHaveLength(count);
  });

  it("exposes a clickable 请顾问出具方案 entry", async () => {
    const wrapper = await mountPage();
    const button = wrapper.get('button[name="request-advisory"]');

    expect(button.text()).toContain("请顾问出具方案");
    expect(button.attributes("disabled")).toBeUndefined();
    await button.trigger("click");
    expect(wrapper.get('button[name="request-advisory"]').text()).toContain("请顾问出具方案");
  });

  it("submits a 方案请求 under the current filters and shows the resulting status", async () => {
    submitAdvisoryRequest.mockResolvedValue(makeRequest());
    const wrapper = await mountPage();

    await wrapper.get('select[name="product_type"]').setValue("债券基金");
    await wrapper.get('button[name="request-advisory"]').trigger("click");
    await flushPromises();

    expect(submitAdvisoryRequest).toHaveBeenCalledWith({ product_type: "债券基金" });
    const panel = wrapper.get('[data-testid="advisory-request"]').text();
    expect(panel).toContain("待处理");
    expect(panel).toContain("AR20260915A1B2C3");
    expect(panel).toContain("债券基金");
  });

  it("shows the status of a 方案请求 submitted earlier", async () => {
    listAdvisoryRequests.mockResolvedValue({
      requests: [
        makeRequest({ status: "处理中" }),
        makeRequest({ id: 2, request_no: "AR20260914AAAAAA", status: "已完成" }),
      ],
    });
    const wrapper = await mountPage();

    expect(submitAdvisoryRequest).not.toHaveBeenCalled();
    const panel = wrapper.get('[data-testid="advisory-request"]').text();
    expect(panel).toContain("处理中");
    expect(panel).toContain("AR20260915A1B2C3");
  });

  it("surfaces a failure to submit the 方案请求", async () => {
    submitAdvisoryRequest.mockRejectedValue(
      new ApiError({ code: 1002, message: "方案请求提交失败", data: null, trace_id: "" }),
    );
    const wrapper = await mountPage();

    await wrapper.get('button[name="request-advisory"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="advisory-error"]').text()).toContain("方案请求提交失败");
  });

  it("explains that empty results come from filters that are too strict", async () => {
    listProducts.mockResolvedValue({ products: [] });
    const wrapper = await mountPage();

    expect(wrapper.find("table").exists()).toBe(false);
    const hint = wrapper.get('[data-testid="empty-hint"]').text();
    expect(hint).toContain("过严");
    expect(hint).toContain("放宽");
    expect(wrapper.find('[data-testid="not-recommendation"]').text()).toBe(DISCLAIMER);
  });

  it("only offers objective disclosed filters", async () => {
    const wrapper = await mountPage();
    const names = wrapper.findAll("form select, form input").map((node) => node.attributes("name"));

    expect(names).toEqual([
      "product_type",
      "risk_level",
      "max_term_days",
      "min_amount",
      "min_expected_return",
    ]);
    expect(wrapper.text()).not.toContain("适合我的");
    expect(wrapper.text()).not.toContain("推荐指数");
  });

  it("opens product detail with the full disclosed elements", async () => {
    const listed = makeProduct();
    const detailed = makeProduct({ fund_manager: "吴宁" });
    listProducts.mockResolvedValue({ products: [listed] });
    getProduct.mockResolvedValue(detailed);
    const wrapper = await mountPage();

    await wrapper.get('button[name="detail-F000001"]').trigger("click");
    await flushPromises();

    expect(getProduct).toHaveBeenCalledWith("F000001");
    const detail = wrapper.get('[data-testid="product-detail"]').text();
    expect(detail).toContain("F000001");
    expect(detail).toContain("货币基金");
    expect(detail).toContain("R1");
    expect(detail).toContain("2.1000");
    expect(detail).toContain("0");
    expect(detail).toContain("1000.00");
    expect(detail).toContain("0.2500");
    expect(detail).toContain("吴宁");
  });
});
