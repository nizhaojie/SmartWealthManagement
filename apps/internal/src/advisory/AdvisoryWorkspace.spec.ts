// 顾问的队列与历史：两类内容（方案 / 操作建议）合并在一张表里，各带类型标注，
// 各自的载荷摘要按类型给；「查看」跳到对应的审核页。历史表每行都能点回审核页，
// 放行与驳回记录一视同仁。
//
// 三段列表各是一页（ADR-0024）：待审内容的计数取服务端的 `total`（不是本页条数），
// 翻页只换页码、不牵动另外两段。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { DEFAULT_PAGE_SIZE, type Paginated } from "@wealth/shared";
import { useAuthStore } from "../stores/auth";
import { apiError, stubApiFetch } from "../testing";
import AdvisoryWorkspace from "./AdvisoryWorkspace.vue";
import { useAdvisoryQueueStore } from "./queueStore";
import type { AdvisoryHistoryEntry, PendingRequest, PendingReview } from "./types";

const PENDING_REVIEWS: PendingReview[] = [
  {
    content_type: "方案",
    content_ref: 7,
    draft_id: 7,
    customer_id: 9,
    customer_name: "王小明",
    status: "待审",
    tilt: "均衡",
    generated_at: "2026-09-18T10:00:00",
    waiting_seconds: 90,
  },
  {
    content_type: "操作建议",
    content_ref: 21,
    customer_id: 10,
    customer_name: "李小红",
    status: "待审",
    product_code: "F000001",
    product_name: "稳健增利一号",
    direction: "申购",
    amount: "200000.00",
    generated_at: "2026-09-18T09:00:00",
    waiting_seconds: 3600,
  },
];

const HISTORY: AdvisoryHistoryEntry[] = [
  {
    content_type: "方案",
    content_ref: 7,
    draft_id: 7,
    customer_id: 9,
    customer_name: "王小明",
    action: "放行",
    reason: null,
    decided_at: "2026-09-18T11:00:00",
  },
  {
    content_type: "方案",
    content_ref: 8,
    draft_id: 8,
    customer_id: 10,
    customer_name: "李小红",
    action: "驳回",
    reason: "标的过于集中",
    decided_at: "2026-09-18T12:00:00",
  },
];

/** 请求里带的页码：分页条翻到第几页，取数就该带去第几页。 */
function pageFromUrl(url: string): number {
  const matched = /[?&]page=(\d+)/.exec(url);
  return matched ? Number(matched[1]) : 1;
}

function pageOf<T>(items: T[], total = items.length, page = 1): Paginated<T> {
  return { items, total, page, page_size: DEFAULT_PAGE_SIZE };
}

/** 把一整批记录按 URL 里的页码切一页——服务端切片的替身。 */
function paginate<T>(rows: T[], url: string): Paginated<T> {
  const page = pageFromUrl(url);
  return pageOf(
    rows.slice((page - 1) * DEFAULT_PAGE_SIZE, page * DEFAULT_PAGE_SIZE),
    rows.length,
    page,
  );
}

function manyReviews(count: number): PendingReview[] {
  return Array.from({ length: count }, (_value, index) =>
    pendingReview(index + 1, { customer_name: `客户${index + 1}` }),
  );
}

function pendingReview(id: number, overrides: Partial<PendingReview> = {}): PendingReview {
  return {
    content_type: "方案",
    content_ref: id,
    draft_id: id,
    customer_id: 100 + id,
    customer_name: "王小明",
    status: "待审",
    tilt: "均衡",
    generated_at: "2026-09-18T10:00:00",
    waiting_seconds: 90,
    ...overrides,
  };
}

function historyEntry(id: number): AdvisoryHistoryEntry {
  return {
    content_type: "方案",
    content_ref: id,
    draft_id: id,
    customer_id: 100 + id,
    customer_name: `客户${id}`,
    action: "放行",
    reason: null,
    decided_at: "2026-09-18T11:00:00",
  };
}

function requestRow(id: number): PendingRequest {
  return {
    id,
    request_no: `AR20260918${String(id).padStart(4, "0")}`,
    customer_id: 100 + id,
    customer_name: `客户${id}`,
    filters: { product_type: "债券基金" },
    submitted_at: "2026-09-18T09:00:00",
    waiting_seconds: 600,
  };
}

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;

type StubOptions = {
  queueFails?: boolean;
  requestsFail?: boolean;
  /** 待审内容与历史各自的整批记录：超过一页时由替身按页码切。 */
  reviews?: PendingReview[];
  history?: AdvisoryHistoryEntry[];
  requests?: PendingRequest[];
  /**
   * 自定义待生成请求的响应。
   *
   * 「`total` 不为零而本页为空」这种形态造不出来：`paginate` 是连续切片，页数由条数
   * 定死。越界页只有靠它模拟。
   */
  requestsResponse?: (url: string) => Paginated<PendingRequest>;
};

async function mountWorkspace(options: StubOptions = {}): Promise<VueWrapper> {
  const reviews = options.reviews ?? [];
  const history = options.history ?? [];
  const requests = options.requests ?? [];

  stubApiFetch((url) => {
    if (url.includes("/api/internal/advisory/history")) return paginate(history, url);
    if (url.includes("/api/internal/advisory/queue")) {
      if (options.queueFails) return apiError(500, "投顾队列加载失败");
      return paginate(reviews, url);
    }
    if (url.includes("/api/internal/advisory-requests")) {
      if (options.requestsFail) return apiError(500, "服务内部错误");
      if (options.requestsResponse) return options.requestsResponse(url);
      return paginate(requests, url);
    }
    return undefined;
  });

  pinia = createPinia();
  setActivePinia(pinia);

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/advisory", name: "advisory", component: AdvisoryWorkspace },
      { path: "/advisory/reviews/:draftId", name: "advisory-review", component: { template: "<div />" } },
      {
        path: "/advisory/operation-advice/:adviceId",
        name: "operation-advice-review",
        component: { template: "<div />" },
      },
    ],
  });
  await router.push("/advisory");
  await router.isReady();

  wrapper = mount(AdvisoryWorkspace, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

/** 某一页里的分页条（三段列表各一个，按出现顺序取）。 */
function pager(page: VueWrapper, index: number) {
  return page.findAll(".pagination-bar")[index];
}

async function turnPage(page: VueWrapper, index: number): Promise<void> {
  await pager(page, index).find(".btn-next").trigger("click");
  await flushPromises();
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("投顾工作台的历史记录", () => {
  it("每条记录都有查看入口，放行与驳回都可回看", async () => {
    const page = await mountWorkspace({ history: HISTORY });

    const rows = page.get('[data-testid="history-table"]').findAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(page.findAll('[data-testid="open-history-review"]')).toHaveLength(2);
  });

  it("点放行记录跳到该草稿的审核页", async () => {
    const page = await mountWorkspace({ history: HISTORY });

    await page.findAll('[data-testid="open-history-review"]')[0].trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory-review");
    expect(router.currentRoute.value.params.draftId).toBe("7");
  });

  it("点驳回记录同样跳到该草稿的审核页", async () => {
    const page = await mountWorkspace({ history: HISTORY });

    await page.findAll('[data-testid="open-history-review"]')[1].trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory-review");
    expect(router.currentRoute.value.params.draftId).toBe("8");
  });

  it("没有记录时不渲染查看入口，也不给翻页条", async () => {
    const page = await mountWorkspace();

    expect(page.find('[data-testid="history-table"]').exists()).toBe(false);
    expect(page.findAll('[data-testid="open-history-review"]')).toHaveLength(0);
    expect(page.get('[data-testid="history-empty"]').text()).toContain("还没有审核过的记录");
  });
});

describe("投顾工作台的三段列表分页", () => {
  it("待生成请求超过一页时可翻页，翻到的那一页就是取回来的那一页", async () => {
    const page = await mountWorkspace({
      requests: Array.from({ length: 25 }, (_value, index) => requestRow(index + 1)),
    });

    const table = () => page.get('[data-testid="pending-requests-table"]');
    expect(table().findAll("tbody tr")).toHaveLength(DEFAULT_PAGE_SIZE);
    expect(table().text()).toContain("AR202609180001");

    await turnPage(page, 0);

    expect(table().findAll("tbody tr")).toHaveLength(5);
    expect(table().text()).toContain("AR202609180025");
    expect(table().text()).not.toContain("AR202609180001");
    // 总数不随翻页变：它是过滤后的总数，不是本页条数。
    expect(pager(page, 0).get('[data-testid="pagination-total"]').text()).toBe("共 25 条");
  });

  it("待审内容超过一页时可翻页，计数仍是过滤后的总数", async () => {
    const page = await mountWorkspace({
      reviews: manyReviews(25),
      history: [historyEntry(1)],
      requests: [requestRow(1)],
    });
    const checks = () => page.get('[data-testid="pending-reviews-table"]').findAll("tbody tr");

    expect(checks()).toHaveLength(DEFAULT_PAGE_SIZE);
    expect(page.text()).toContain("待审核（25）");

    await turnPage(page, 1);

    expect(checks()).toHaveLength(5);
    // 数本页会把「还有 25 件在等」说成「20 件」——角标与卡片标题读的都是同一个总数。
    expect(page.text()).toContain("待审核（25）");
    expect(useAdvisoryQueueStore(pinia).pendingReviewCount).toBe(25);
  });

  it("审核历史超过一页时可翻页，且三段互不牵动", async () => {
    const page = await mountWorkspace({
      reviews: manyReviews(25),
      history: Array.from({ length: 25 }, (_value, index) => historyEntry(index + 1)),
      requests: [requestRow(1), requestRow(2)],
    });

    await turnPage(page, 2);

    expect(page.get('[data-testid="history-table"]').findAll("tbody tr")).toHaveLength(5);
    expect(page.get('[data-testid="history-table"]').text()).toContain("客户25");
    // 翻历史不会动另外两段：待审仍在它自己的第 1 页，待生成请求也还在。
    expect(page.get('[data-testid="pending-reviews-table"]').findAll("tbody tr")).toHaveLength(
      DEFAULT_PAGE_SIZE,
    );
    expect(page.get('[data-testid="pending-requests-table"]').findAll("tbody tr")).toHaveLength(2);
  });

  it("空页仍留着分页条：撤掉它，人就困在那一页上", async () => {
    const page = await mountWorkspace({
      requestsResponse: (url) =>
        pageFromUrl(url) === 1 ? pageOf([requestRow(1)], 21) : pageOf([], 21, pageFromUrl(url)),
    });

    await turnPage(page, 0);

    expect(page.find('[data-testid="pending-requests-table"]').exists()).toBe(false);
    // 本页为空而总数不为零：这不是「暂无待生成的方案请求」。
    expect(page.text()).not.toContain("暂无待生成的方案请求");
    expect(pager(page, 0).get('[data-testid="pagination-total"]').text()).toBe("共 21 条");
  });
});

describe("待审队列合并两类内容", () => {
  it("方案与操作建议同表渲染，各行带自己的类型标注", async () => {
    const page = await mountWorkspace({ reviews: PENDING_REVIEWS });

    const rows = page.get('[data-testid="pending-reviews-table"]').findAll("tbody tr");
    expect(rows).toHaveLength(2);

    const types = page.findAll('[data-testid="pending-review-type"]').map((tag) => tag.text());
    expect(types).toEqual(["方案", "操作建议"]);
  });

  it("摘要按类型给：方案说生成侧重，操作建议说产品、方向与金额", async () => {
    const page = await mountWorkspace({ reviews: PENDING_REVIEWS });

    const rows = page.get('[data-testid="pending-reviews-table"]').findAll("tbody tr");
    expect(rows[0].text()).toContain("均衡");
    expect(rows[1].text()).toContain("稳健增利一号");
    expect(rows[1].text()).toContain("申购");
    expect(rows[1].text()).toContain("200,000.00");
  });

  it("等待时长按各自的起点现算，不因为类型不同而换口径", async () => {
    const page = await mountWorkspace({ reviews: PENDING_REVIEWS });

    const rows = page.get('[data-testid="pending-reviews-table"]').findAll("tbody tr");
    expect(rows[0].text()).toContain("1 分钟");
    expect(rows[1].text()).toContain("1 小时 0 分钟");
  });

  it("操作建议那一行跳到它自己的审核页", async () => {
    const page = await mountWorkspace({ reviews: PENDING_REVIEWS });

    await page.findAll('[data-testid="open-review"]')[1].trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("operation-advice-review");
    expect(router.currentRoute.value.params.adviceId).toBe("21");
  });

  it("方案那一行仍然跳方案审核页", async () => {
    const page = await mountWorkspace({ reviews: PENDING_REVIEWS });

    await page.findAll('[data-testid="open-review"]')[0].trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory-review");
    expect(router.currentRoute.value.params.draftId).toBe("7");
  });
});

// 计数只在一处算：卡片的标题与壳的角标都读同一个 store，页面自己不再现算列表长度。
describe("待审内容的待办计数", () => {
  it("取数之后计数等于队列条数，卡片标题读的就是这个数", async () => {
    const page = await mountWorkspace({ reviews: PENDING_REVIEWS, history: HISTORY });

    expect(useAdvisoryQueueStore(pinia).pendingReviewCount).toBe(2);
    expect(page.text()).toContain("待审核（2）");
  });

  it("队列接口失败时计数是 undefined 而不是 0，失败在页面上有一条横幅", async () => {
    const page = await mountWorkspace({ queueFails: true, history: HISTORY });
    const queue = useAdvisoryQueueStore(pinia);

    expect(queue.failed).toBe(true);
    expect(queue.pendingReviewCount).toBeUndefined();
    // 「（0）」与「暂无」是同一句断言（「没有待办」），失败时我们并不知道有几件，那张卡不该说。
    expect(page.text()).not.toContain("待审核（0）");
    expect(page.text()).not.toContain("暂无待审核内容");
    expect(page.get('[data-testid="queue-error"]').text()).toBe("投顾队列加载失败");
  });

  it("待生成请求拉不到时也不说暂无，并说明是哪一段失败", async () => {
    const page = await mountWorkspace({ requestsFail: true });

    expect(page.text()).not.toContain("待生成的方案请求（0）");
    expect(page.text()).not.toContain("暂无待生成的方案请求");
    expect(page.get('[data-testid="queue-unavailable"]').text()).toBe("队列暂不可用");
    const banner = page.get('[data-testid="queue-error"]').text();
    expect(banner).toContain("方案请求加载失败");
    expect(banner).toContain("服务内部错误");
  });

  it("登出后计数清空，角标不带着上一位员工的数字进入新会话", async () => {
    await mountWorkspace({ reviews: PENDING_REVIEWS, history: HISTORY });
    const queue = useAdvisoryQueueStore(pinia);
    expect(queue.pendingReviewCount).toBe(2);

    await useAuthStore(pinia).logout();

    expect(queue.pendingReviewCount).toBeUndefined();
    expect(queue.pendingReviews).toHaveLength(0);
  });
});
