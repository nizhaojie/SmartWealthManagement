// 顾问的队列与历史：两类内容（方案 / 操作建议）合并在一张表里，各带类型标注，
// 各自的载荷摘要按类型给；「查看」跳到对应的审核页。历史表每行都能点回审核页，
// 放行与驳回记录一视同仁。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { apiError, stubApiFetch } from "../testing";
import AdvisoryWorkspace from "./AdvisoryWorkspace.vue";
import { useAdvisoryQueueStore } from "./queueStore";
import type { AdvisoryHistoryEntry, PendingReview } from "./types";

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

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;

async function mountWorkspace(
  history: AdvisoryHistoryEntry[] = HISTORY,
  pendingReviews: PendingReview[] = [],
  options: { queueFails?: boolean } = {},
): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/api/internal/advisory/history")) return { history };
    if (url.includes("/api/internal/advisory/queue")) {
      if (options.queueFails) return apiError(500, "投顾队列加载失败");
      return { pending_requests: [], pending_reviews: pendingReviews };
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
    const page = await mountWorkspace();

    const rows = page.get('[data-testid="history-table"]').findAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(page.findAll('[data-testid="open-history-review"]')).toHaveLength(2);
  });

  it("点放行记录跳到该草稿的审核页", async () => {
    const page = await mountWorkspace();

    await page.findAll('[data-testid="open-history-review"]')[0].trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory-review");
    expect(router.currentRoute.value.params.draftId).toBe("7");
  });

  it("点驳回记录同样跳到该草稿的审核页", async () => {
    const page = await mountWorkspace();

    await page.findAll('[data-testid="open-history-review"]')[1].trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory-review");
    expect(router.currentRoute.value.params.draftId).toBe("8");
  });

  it("没有记录时不渲染查看入口", async () => {
    const page = await mountWorkspace([]);

    expect(page.find('[data-testid="history-table"]').exists()).toBe(false);
    expect(page.findAll('[data-testid="open-history-review"]')).toHaveLength(0);
  });
});

describe("待审队列合并两类内容", () => {
  it("方案与操作建议同表渲染，各行带自己的类型标注", async () => {
    const page = await mountWorkspace(HISTORY, PENDING_REVIEWS);

    const rows = page.get('[data-testid="pending-reviews-table"]').findAll("tbody tr");
    expect(rows).toHaveLength(2);

    const types = page.findAll('[data-testid="pending-review-type"]').map((tag) => tag.text());
    expect(types).toEqual(["方案", "操作建议"]);
  });

  it("摘要按类型给：方案说生成侧重，操作建议说产品、方向与金额", async () => {
    const page = await mountWorkspace(HISTORY, PENDING_REVIEWS);

    const rows = page.get('[data-testid="pending-reviews-table"]').findAll("tbody tr");
    expect(rows[0].text()).toContain("均衡");
    expect(rows[1].text()).toContain("稳健增利一号");
    expect(rows[1].text()).toContain("申购");
    expect(rows[1].text()).toContain("200,000.00");
  });

  it("等待时长按各自的起点现算，不因为类型不同而换口径", async () => {
    const page = await mountWorkspace(HISTORY, PENDING_REVIEWS);

    const rows = page.get('[data-testid="pending-reviews-table"]').findAll("tbody tr");
    expect(rows[0].text()).toContain("1 分钟");
    expect(rows[1].text()).toContain("1 小时 0 分钟");
  });

  it("操作建议那一行跳到它自己的审核页", async () => {
    const page = await mountWorkspace(HISTORY, PENDING_REVIEWS);

    await page.findAll('[data-testid="open-review"]')[1].trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("operation-advice-review");
    expect(router.currentRoute.value.params.adviceId).toBe("21");
  });

  it("方案那一行仍然跳方案审核页", async () => {
    const page = await mountWorkspace(HISTORY, PENDING_REVIEWS);

    await page.findAll('[data-testid="open-review"]')[0].trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory-review");
    expect(router.currentRoute.value.params.draftId).toBe("7");
  });
});

// 计数只在一处算：卡片的标题与壳的角标都读同一个 store，页面自己不再现算列表长度。
describe("待审内容的待办计数", () => {
  it("取数之后计数等于队列条数，卡片标题读的就是这个数", async () => {
    const page = await mountWorkspace(HISTORY, PENDING_REVIEWS);

    expect(useAdvisoryQueueStore(pinia).pendingReviewCount).toBe(2);
    expect(page.text()).toContain("待审核（2）");
  });

  it("队列接口失败时计数是 undefined 而不是 0，失败在页面上有一条横幅", async () => {
    const page = await mountWorkspace(HISTORY, [], { queueFails: true });
    const queue = useAdvisoryQueueStore(pinia);

    expect(queue.failed).toBe(true);
    expect(queue.pendingReviewCount).toBeUndefined();
    // 「（0）」与「暂无」是同一句断言（「没有待办」），失败时我们并不知道有几件，两张卡都不该说。
    expect(page.text()).not.toContain("待审核（0）");
    expect(page.text()).not.toContain("待生成的方案请求（0）");
    expect(page.text()).not.toContain("暂无待审核内容");
    expect(page.text()).not.toContain("暂无待生成的方案请求");
    expect(page.findAll('[data-testid="queue-unavailable"]')).toHaveLength(2);
    expect(page.get('[data-testid="queue-error"]').text()).toBe("投顾队列加载失败");
  });

  it("登出后计数清空，角标不带着上一位员工的数字进入新会话", async () => {
    await mountWorkspace(HISTORY, PENDING_REVIEWS);
    const queue = useAdvisoryQueueStore(pinia);
    expect(queue.pendingReviewCount).toBe(2);

    await useAuthStore(pinia).logout();

    expect(queue.pendingReviewCount).toBeUndefined();
    expect(queue.pendingReviews).toHaveLength(0);
  });
});
