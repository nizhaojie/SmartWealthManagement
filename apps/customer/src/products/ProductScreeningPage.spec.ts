// 产品筛选页的合规呈现面：适当性说明与「不是推荐」常驻，且清单不提供任何可排序表头。
// 方案请求的进度列表不在这页——它迁去了「我的方案」页，这里只留提交按钮。
// 清单分页（ADR-0024）：排序恒按 product_code 升序（ADR-0005），分页只是在这条固定
// 顺序上切片——护栏测试 4 的 seam（不接受客户端排序参数）不能被翻页动摇。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ApiError, DEFAULT_PAGE_SIZE, type PageQuery, type Paginated } from "@wealth/shared";
import type { AdvisoryRequest } from "../advisory/types";
import type { CandidatePool, Product } from "./types";

const { listProducts, getProduct, getCandidatePool } = vi.hoisted(() => ({
  listProducts: vi.fn(),
  getProduct: vi.fn(),
  getCandidatePool: vi.fn(),
}));

const { submitAdvisoryRequest } = vi.hoisted(() => ({ submitAdvisoryRequest: vi.fn() }));

// 保留模块里的纯函数（compactFilters）——只桩掉发请求的那几个。
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api")>()),
  listProducts,
  getProduct,
  getCandidatePool,
}));
vi.mock("../advisory/api", () => ({ submitAdvisoryRequest }));

import ProductScreeningPage from "./ProductScreeningPage.vue";

const DISCLAIMER = "这是符合条件的产品清单，不是推荐";

function pageOf(items: Product[], total = items.length, query?: PageQuery): Paginated<Product> {
  return {
    items,
    total,
    page: query?.page ?? 1,
    page_size: query?.page_size ?? DEFAULT_PAGE_SIZE,
  };
}

/** 按查询里的页码切一页——服务端切片的替身，list 已按 product_code 升序排好。 */
function productPages(products: Product[]): (query: PageQuery) => Promise<Paginated<Product>> {
  return (query) =>
    Promise.resolve(
      pageOf(
        products.slice((query.page - 1) * query.page_size, query.page * query.page_size),
        products.length,
        query,
      ),
    );
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

function makeCandidatePool(overrides: Partial<CandidatePool> = {}): CandidatePool {
  return {
    assessment_id: 1,
    customer_risk_level: "C4",
    allowed_product_risk_levels: ["R1", "R2", "R3", "R4"],
    products: [],
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

const Blank = { render: () => h("div") };

let router: Router;

/** 页面提交成功后要跳转，因此每个用例都带一张路由表（详情页不在本文件覆盖范围内）。 */
async function mountPage(): Promise<VueWrapper> {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/products", name: "products", component: Blank },
      { path: "/advisory", name: "advisory", component: Blank },
    ],
  });
  await router.push("/products");
  await router.isReady();

  const wrapper = mount(ProductScreeningPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

// jsdom 不实现 scrollIntoView，这里替身记录「谁被滚进了视野」。
const scrollIntoView = vi.fn();

async function turnPage(page: VueWrapper): Promise<void> {
  await page.get(".pagination-bar .btn-next").trigger("click");
  await flushPromises();
}

describe("ProductScreeningPage", () => {
  beforeEach(() => {
    listProducts.mockReset();
    getProduct.mockReset();
    getCandidatePool.mockReset();
    submitAdvisoryRequest.mockReset();
    scrollIntoView.mockReset();
    Element.prototype.scrollIntoView = scrollIntoView;

    listProducts.mockResolvedValue(pageOf([makeProduct()]));
    getCandidatePool.mockResolvedValue(makeCandidatePool());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });

  it("states the suitable range the customer may buy, next to the not-a-recommendation notice", async () => {
    const wrapper = await mountPage();

    const note = wrapper.get('[data-testid="suitability-note"]').text();
    expect(note).toContain("C4");
    expect(note).toContain("R1");
    expect(note).toContain("R4");
    expect(note).toContain("越级产品不会出现");
    expect(wrapper.get('[data-testid="not-recommendation"]').text()).toBe(DISCLAIMER);
  });

  it("still explains the range is not known when the suitability range cannot be read", async () => {
    getCandidatePool.mockRejectedValue(
      new ApiError({ code: 404, message: "暂无风险测评记录", data: null, trace_id: "" }),
    );
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="suitability-note"]').text()).toContain("风险测评");
  });

  it.each([1, 2, 20])("keeps the not-a-recommendation notice when there are %s products", async (count) => {
    listProducts.mockResolvedValue(pageOf(productsOfCount(count)));
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="not-recommendation"]').text()).toBe(DISCLAIMER);
    expect(wrapper.findAll("tbody tr")).toHaveLength(count);
  });

  it("does not render sortable table headers, so clicking 业绩基准 cannot reorder rows", async () => {
    listProducts.mockResolvedValue(
      pageOf([
        makeProduct({ product_code: "F000001", expected_return: "2.1000" }),
        makeProduct({
          product_code: "F000002",
          product_name: "天玑债券基金",
          product_type: "债券基金",
          risk_level: "R2",
          expected_return: "18.0000",
        }),
      ]),
    );
    const wrapper = await mountPage();

    const headers = wrapper.findAll("table thead th");
    expect(headers.length).toBeGreaterThan(0);
    expect(wrapper.findAll("th[aria-sort]")).toHaveLength(0);
    expect(wrapper.findAll(".caret-wrapper")).toHaveLength(0);
    for (const header of headers) {
      expect(header.find("button").exists()).toBe(false);
    }

    const rowsBefore = wrapper.findAll("tbody tr").map((row) => row.text());
    const benchmarkHeader = headers.find((header) => header.text().includes("业绩基准"));
    expect(benchmarkHeader).toBeDefined();
    await benchmarkHeader!.trigger("click");
    await flushPromises();

    expect(wrapper.findAll("tbody tr").map((row) => row.text())).toEqual(rowsBefore);
    expect(wrapper.findAll("tbody tr")[0].text()).toContain("F000001");
  });

  it("sends the customer to 我的方案 after the 方案请求 is submitted", async () => {
    submitAdvisoryRequest.mockResolvedValue(makeRequest());
    const wrapper = await mountPage();

    await wrapper.get('button[name="request-advisory"]').trigger("click");
    await flushPromises();

    expect(submitAdvisoryRequest).toHaveBeenCalledWith({});
    expect(router.currentRoute.value.name).toBe("advisory");
    expect(router.currentRoute.value.path).toBe("/advisory");
    // 请求列表已经交出去了：这页不再自己渲染它。
    expect(wrapper.find('[data-testid="advisory-requests"]').exists()).toBe(false);
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

  // 详情面板挂在清单下方，点「查看」时它落在视口之外——「按钮点了没反应」就是这么来的。
  it("brings the opened product detail into view when 查看 is clicked", async () => {
    getProduct.mockResolvedValue(makeProduct({ product_name: "天枢货币基金" }));
    const wrapper = await mountPage();

    await wrapper.get('[data-testid="product-detail-entry"]').trigger("click");
    await flushPromises();

    expect(getProduct).toHaveBeenCalledWith("F000001");
    const detail = wrapper.get('[data-testid="product-detail"]');
    expect(detail.text()).toContain("天枢货币基金");

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "nearest" });
    // 被滚动的是承载详情的元素本身，不是别的什么。
    const scrolled = scrollIntoView.mock.instances[0] as unknown as HTMLElement;
    expect(scrolled.contains(detail.element)).toBe(true);
  });

  it("explains that empty results come from filters that are too strict", async () => {
    listProducts.mockResolvedValue(pageOf([]));
    const wrapper = await mountPage();

    expect(wrapper.find("table").exists()).toBe(false);
    const hint = wrapper.get('[data-testid="empty-hint"]').text();
    expect(hint).toContain("过严");
    expect(hint).toContain("放宽");
    expect(wrapper.get('[data-testid="not-recommendation"]').text()).toBe(DISCLAIMER);
  });

  it("asks for the first page and shows the server total", async () => {
    listProducts.mockResolvedValue(pageOf([makeProduct()], 45));
    const wrapper = await mountPage();

    expect(listProducts).toHaveBeenCalledWith({ page: 1, page_size: DEFAULT_PAGE_SIZE }, expect.anything());
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
  });

  it("turns the page while keeping the product-code order", async () => {
    listProducts.mockImplementation(productPages(productsOfCount(25)));
    const wrapper = await mountPage();

    await turnPage(wrapper);

    expect(listProducts).toHaveBeenLastCalledWith(
      { page: 2, page_size: DEFAULT_PAGE_SIZE },
      expect.anything(),
    );
    const codesOnPage2 = wrapper.findAll("tbody tr").map((row) => row.get("td").text());
    expect(codesOnPage2).toEqual(
      productsOfCount(25)
        .slice(20, 25)
        .map((product) => product.product_code),
    );
  });

  it("returns to the first page after the filters are reapplied", async () => {
    listProducts.mockImplementation(productPages(productsOfCount(25)));
    const wrapper = await mountPage();

    await turnPage(wrapper);
    expect(listProducts).toHaveBeenLastCalledWith(
      { page: 2, page_size: DEFAULT_PAGE_SIZE },
      expect.anything(),
    );

    await wrapper.get('form.filters').trigger("submit");
    await flushPromises();

    expect(listProducts).toHaveBeenLastCalledWith(
      { page: 1, page_size: DEFAULT_PAGE_SIZE },
      expect.anything(),
    );
  });

  it("keeps the pager on a page that turned out to be empty, without losing the total", async () => {
    // 翻到的那一页没有产品（越界，或记录在这两次取数之间变少了）：服务端给空 items
    // 而 total 不变。空态要说清楚，但翻页条必须留着——撤掉它，人就困在这一页上。
    listProducts.mockImplementation((query) =>
      Promise.resolve(pageOf(query.page === 1 ? [makeProduct()] : [], 21, query)),
    );
    const wrapper = await mountPage();

    await turnPage(wrapper);

    expect(wrapper.find('[data-testid="products-table"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="empty-hint"]').text()).toContain("没有符合条件的产品");
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 21 条");
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(true);
  });

  it("maps a 404 from the products page to the missing-assessment explanation", async () => {
    listProducts.mockRejectedValue(
      new ApiError({ code: 404, message: "暂无风险测评记录", data: null, trace_id: "" }),
    );
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="products-error"]').text()).toContain("尚未完成风险测评");
  });
});
