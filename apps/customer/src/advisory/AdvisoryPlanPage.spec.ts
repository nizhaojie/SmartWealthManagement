// 「我的方案」页的三种首屏：有定稿 / 只有请求 / 都无。
// 两个分区（已放行方案、方案请求进度）不合成一条时间线，空状态也分两级（Q6、Q13）。
// 两个分区各自一页（ADR-0024）：翻其中一页不牵动另一页，空状态判的是「一份都没有」。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ApiError, DEFAULT_PAGE_SIZE, type PageQuery, type Paginated } from "@wealth/shared";
import type { AdvisoryRequest, ReleasedPlan } from "./types";

const { listReleasedPlans, listAdvisoryRequests } = vi.hoisted(() => ({
  listReleasedPlans: vi.fn(),
  listAdvisoryRequests: vi.fn(),
}));

vi.mock("./api", () => ({ listReleasedPlans, listAdvisoryRequests }));

import AdvisoryPlanPage from "./AdvisoryPlanPage.vue";

const Blank = { render: () => h("div") };

function pageOf<T>(items: T[], total = items.length, query?: PageQuery): Paginated<T> {
  return {
    items,
    total,
    page: query?.page ?? 1,
    page_size: query?.page_size ?? DEFAULT_PAGE_SIZE,
  };
}

function makePlan(overrides: Partial<ReleasedPlan> = {}): ReleasedPlan {
  return {
    id: 12,
    advisor_name: "李文",
    candidates: [
      {
        product_code: "F000001",
        product_name: "天枢货币基金",
        product_type: "货币基金",
        risk_level: "R1",
        expected_return: "2.1000",
        term_days: 0,
      },
      {
        product_code: "F000002",
        product_name: "天玑债券基金",
        product_type: "债券基金",
        risk_level: "R2",
        expected_return: "3.5000",
        term_days: 180,
      },
    ],
    allocation_suggestion: { 债券: 60 },
    released_at: "2026-09-10T09:00:00",
    disclaimer: "本方案由理财顾问出具，仅供参考",
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

/** 按查询里的页码切一页——服务端切片的替身。 */
function planPages(plans: ReleasedPlan[]): (query: PageQuery) => Promise<Paginated<ReleasedPlan>> {
  return (query) =>
    Promise.resolve(
      pageOf(
        plans.slice((query.page - 1) * query.page_size, query.page * query.page_size),
        plans.length,
        query,
      ),
    );
}

function requestPages(
  requests: AdvisoryRequest[],
): (query: PageQuery) => Promise<Paginated<AdvisoryRequest>> {
  return (query) =>
    Promise.resolve(
      pageOf(
        requests.slice((query.page - 1) * query.page_size, query.page * query.page_size),
        requests.length,
        query,
      ),
    );
}

let router: Router;
let activeWrapper: VueWrapper | null = null;

async function mountPage(): Promise<VueWrapper> {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/advisory", name: "advisory", component: Blank },
      { path: "/advisory/plans/:finalId", name: "advisory-plan", component: Blank },
      { path: "/products", name: "products", component: Blank },
    ],
  });
  await router.push("/advisory");
  await router.isReady();
  activeWrapper = mount(AdvisoryPlanPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return activeWrapper;
}

/** 两个分区各一个分页条，按出现顺序取。 */
function pager(page: VueWrapper, index: number) {
  return page.findAll(".pagination-bar")[index];
}

async function turnPage(page: VueWrapper, index: number): Promise<void> {
  await pager(page, index).find(".btn-next").trigger("click");
  await flushPromises();
}

describe("AdvisoryPlanPage", () => {
  beforeEach(() => {
    listReleasedPlans.mockReset();
    listAdvisoryRequests.mockReset();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("summarises each released plan with 出具时间、出具顾问 and 产品数", async () => {
    listReleasedPlans.mockResolvedValue(pageOf([makePlan()]));
    listAdvisoryRequests.mockResolvedValue(pageOf([]));
    const wrapper = await mountPage();

    const row = wrapper.get('[data-testid="released-plan"]');
    expect(row.text()).toContain("出具顾问：李文");
    expect(row.text()).toContain("产品数：2");
    expect(row.text()).toContain("出具时间：");
    expect(wrapper.findAll('[data-testid="released-plan"]')).toHaveLength(1);
    // 没有任何请求时不该出现请求分区，也不该出现引导空状态。
    expect(wrapper.find('[data-testid="advisory-requests"]').exists()).toBe(false);
    expect(wrapper.text()).not.toContain("还没有提交过方案请求");
  });

  it("renders the 方案请求进度 when there is no released plan yet", async () => {
    listReleasedPlans.mockResolvedValue(pageOf([]));
    listAdvisoryRequests.mockResolvedValue(pageOf([makeRequest()]));
    const wrapper = await mountPage();

    expect(wrapper.find('[data-testid="released-plans"]').exists()).toBe(false);
    const request = wrapper.get('[data-testid="advisory-request"]').text();
    expect(request).toContain("待处理");
    expect(request).toContain("AR20260915A1B2C3");
    expect(request).toContain("债券基金");
    // 请求已经在等顾问了，就不该再说「还没有提交过方案请求」。
    expect(wrapper.text()).not.toContain("还没有提交过方案请求");
  });

  it("guides to 产品筛选 when there is neither a plan nor a request", async () => {
    listReleasedPlans.mockResolvedValue(pageOf([]));
    listAdvisoryRequests.mockResolvedValue(pageOf([]));
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="plans-empty"]').text()).toContain("还没有提交过方案请求");

    await wrapper.get('button[name="go-products"]').trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/products");
  });

  it("opens a plan at its own route", async () => {
    listReleasedPlans.mockResolvedValue(pageOf([makePlan({ id: 12 })]));
    listAdvisoryRequests.mockResolvedValue(pageOf([]));
    const wrapper = await mountPage();

    await wrapper.get('[data-testid="released-plan"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory-plan");
    expect(router.currentRoute.value.params.finalId).toBe("12");
  });

  it("asks for the first page of each section and shows the server totals", async () => {
    listReleasedPlans.mockResolvedValue(pageOf([makePlan()], 25));
    listAdvisoryRequests.mockResolvedValue(pageOf([makeRequest()], 12));
    const wrapper = await mountPage();

    expect(listReleasedPlans).toHaveBeenCalledWith({ page: 1, page_size: DEFAULT_PAGE_SIZE });
    expect(listAdvisoryRequests).toHaveBeenCalledWith({ page: 1, page_size: DEFAULT_PAGE_SIZE });
    const totals = wrapper.findAll('[data-testid="pagination-total"]').map((node) => node.text());
    expect(totals).toEqual(["共 25 条", "共 12 条"]);
  });

  it("turns a section's page without touching the other section's page", async () => {
    listReleasedPlans.mockImplementation(
      planPages(Array.from({ length: 25 }, (_value, index) => makePlan({ id: index + 1 }))),
    );
    listAdvisoryRequests.mockImplementation(
      requestPages(
        Array.from({ length: 25 }, (_value, index) =>
          makeRequest({ id: index + 1, request_no: `AR-${index + 1}` }),
        ),
      ),
    );
    const wrapper = await mountPage();

    // 第 0 个分页条是「已放行方案」，第 1 个是「方案请求进度」。
    await turnPage(wrapper, 1);

    expect(listAdvisoryRequests).toHaveBeenLastCalledWith({
      page: 2,
      page_size: DEFAULT_PAGE_SIZE,
    });
    expect(wrapper.findAll('[data-testid="advisory-request"]')).toHaveLength(DEFAULT_PAGE_SIZE);
    expect(wrapper.get('[data-testid="advisory-requests"]').text()).toContain("AR-20");
    // 翻请求不牵动方案那一段：它还在第 1 页，也没有被重新取过。
    expect(listReleasedPlans).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="released-plans"]').text()).toContain("出具顾问：李文");
    expect(pager(wrapper, 0).get('[data-testid="pagination-total"]').text()).toBe("共 25 条");
  });

  it("turns the plan section's own page and keeps the request section alone", async () => {
    listReleasedPlans.mockImplementation(
      planPages(Array.from({ length: 25 }, (_value, index) => makePlan({ id: index + 1 }))),
    );
    listAdvisoryRequests.mockImplementation(
      requestPages([makeRequest({ request_no: "AR-KEEP" })]),
    );
    const wrapper = await mountPage();

    await turnPage(wrapper, 0);

    expect(listReleasedPlans).toHaveBeenLastCalledWith({ page: 2, page_size: DEFAULT_PAGE_SIZE });
    expect(listAdvisoryRequests).toHaveBeenCalledTimes(1);
    expect(wrapper.get('[data-testid="advisory-requests"]').text()).toContain("AR-KEEP");
  });

  it("does not show an empty state for a page that is empty but not the whole list", async () => {
    listReleasedPlans.mockImplementation((query: PageQuery) =>
      Promise.resolve(
        pageOf(query.page === 1 ? [makePlan()] : [], 21, query),
      ),
    );
    listAdvisoryRequests.mockResolvedValue(pageOf([]));
    const wrapper = await mountPage();

    await turnPage(wrapper, 0);

    expect(wrapper.find('[data-testid="released-plans"]').exists()).toBe(false);
    // 这一页没有内容而总共有 21 份：这不是「一份方案都没有」。
    expect(wrapper.find('[data-testid="plans-empty"]').exists()).toBe(false);
    expect(pager(wrapper, 0).get('[data-testid="pagination-total"]').text()).toBe("共 21 条");
  });

  // 「拉取失败」不是「什么都没有」：把接口故障说成「你还没提过请求」会让客户去重复提交。
  it("does not present a failed plan load as an empty state", async () => {
    listReleasedPlans.mockRejectedValue(
      new ApiError({ code: 500, message: "服务内部错误", data: null, trace_id: "" }),
    );
    listAdvisoryRequests.mockResolvedValue(pageOf([]));
    const wrapper = await mountPage();

    expect(wrapper.get('[data-testid="plans-error"]').text()).toContain("服务内部错误");
    expect(wrapper.find('[data-testid="plans-empty"]').exists()).toBe(false);
  });

  // 尚无定稿时，请求进度就是页面上唯一该有内容的位置——它拉不到时不能只剩页头。
  it("explains a failed 方案请求进度 load instead of leaving a blank page", async () => {
    listReleasedPlans.mockResolvedValue(pageOf([]));
    listAdvisoryRequests.mockRejectedValue(
      new ApiError({ code: 500, message: "服务内部错误", data: null, trace_id: "" }),
    );
    const wrapper = await mountPage();

    const notice = wrapper.get('[data-testid="requests-error"]').text();
    expect(notice).toContain("方案请求进度加载失败");
    expect(notice).toContain("服务内部错误");
    expect(wrapper.find('[data-testid="plans-empty"]').exists()).toBe(false);
  });
});
