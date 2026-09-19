// 护栏 5「未审核内容不可送达」在前端的落点：
// AI 原稿与顾问定稿两个版本分别可见且都留存；放行与驳回各自走通；驳回理由为空提交被拒。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ACCOUNT_MANAGER, ADVISOR, type EmployeeRole } from "../auth/identity";
import { useAuthStore } from "../stores/auth";
import { apiError, requestedUrls, stubApiFetch } from "../testing";
import AdvisoryReviewPage from "./AdvisoryReviewPage.vue";

const DRAFT = {
  id: 7,
  customer_id: 9,
  advisor_id: 2,
  tilt: "均衡",
  content_classification: "投顾内容",
  candidates: [
    {
      product_code: "P001",
      product_name: "稳健增利一号",
      product_type: "债券基金",
      risk_level: "R2",
      expected_return: "3.5",
      term_days: 365,
      composite_score: 88.2,
      score_breakdown: [
        { dimension: "风险匹配", raw_value: "C3 / R2", score: 90, weight: 0.3, contribution: 27 },
      ],
      reason: "与客户目标配置一致",
    },
  ],
  allocation_suggestion: { 债券: 60, 股票: 20 },
  warnings: [{ code: "CONCENTRATION", message: "债券集中度偏高" }],
  profile_computed_at: "2026-09-18T09:00:00",
  candidate_pool_snapshot: {},
  generated_at: "2026-09-18T10:00:00",
  advisory_request_id: null,
  disclaimer: "本方案为投顾内容，须经审核后送达。",
};

const FINAL = {
  id: 1,
  draft_id: 7,
  customer_id: 9,
  advisor_id: 2,
  advisor_name: "张顾问",
  content_classification: "投顾内容",
  candidates: [
    {
      product_code: "P001",
      product_name: "稳健增利一号（定稿）",
      product_type: "债券基金",
      risk_level: "R2",
      expected_return: "3.5",
      term_days: 365,
      composite_score: 88.2,
      score_breakdown: [],
      reason: "与客户目标配置一致",
    },
  ],
  allocation_suggestion: { 债券: 60, 股票: 20 },
  warnings: [],
  released_at: "2026-09-18T11:00:00",
  disclaimer: "本方案为投顾内容，须经审核后送达。",
};

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;
let responded: { review?: unknown; draft?: unknown; final?: unknown } = {};

async function mountPage(role: EmployeeRole): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/drafts/7/review")) return responded.review ?? { draft_id: 7, status: "待审" };
    if (url.includes("/drafts/7/final")) return responded.final ?? FINAL;
    if (url.includes("/drafts/7/comments")) return { comments: [] };
    if (url.includes("/drafts/7/release")) return FINAL;
    if (url.includes("/drafts/7/reject")) return { draft_id: 7, status: "已驳回", reason: "标的过于集中" };
    if (url.includes("/drafts/7")) return responded.draft ?? DRAFT;
    return undefined;
  });

  pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().currentEmployee = { real_name: "测试员工", employee_role: role };

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/advisory/reviews/:draftId", name: "advisory-review", component: AdvisoryReviewPage },
      { path: "/advisory", name: "advisory", component: { template: "<div />" } },
    ],
  });
  await router.push("/advisory/reviews/7");
  await router.isReady();

  wrapper = mount(AdvisoryReviewPage, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  localStorage.clear();
  responded = {};
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("审核页", () => {
  it("AI 原稿与顾问编辑版本并排可见", async () => {
    const page = await mountPage(ADVISOR);

    expect(page.get('[data-testid="original-panel"]').text()).toContain("稳健增利一号");
    expect(page.find('[data-testid="edited-panel"]').exists()).toBe(true);
    expect(page.findAll('[data-testid="candidate-include"]').length).toBe(1);
    expect(page.get('[data-testid="review-status"]').text()).toContain("待审");
  });

  it("画像警告原样透传", async () => {
    const page = await mountPage(ADVISOR);

    expect(page.get('[data-testid="draft-warning"]').text()).toContain("债券集中度偏高");
  });

  it("放行后出现顾问定稿，AI 原稿仍然留存", async () => {
    const page = await mountPage(ADVISOR);

    await page.get('[data-testid="release"]').trigger("click");
    await flushPromises();

    expect(page.get('[data-testid="final-panel"]').text()).toContain("稳健增利一号（定稿）");
    expect(page.get('[data-testid="review-status"]').text()).toContain("已放行");
    // 两版本留存：定稿出现不等于原稿消失。
    expect(page.get('[data-testid="original-panel"]').text()).toContain("稳健增利一号");
    expect(page.find('[data-testid="review-decision"]').exists()).toBe(false);
  });

  it("驳回理由为空时提交被拒，接口不会被调用", async () => {
    const page = await mountPage(ADVISOR);
    const fetchMock = vi.mocked(globalThis.fetch);

    expect(page.get('[data-testid="reject"]').attributes("disabled")).toBeDefined();
    await page.get('[data-testid="reject"]').trigger("click");
    await flushPromises();

    expect(requestedUrls(fetchMock, "/reject")).toHaveLength(0);
    expect(page.get('[data-testid="review-status"]').text()).toContain("待审");
  });

  it("填了理由就能驳回，理由随请求发出", async () => {
    const page = await mountPage(ADVISOR);
    const fetchMock = vi.mocked(globalThis.fetch);

    await page.get('[data-testid="reject-reason"]').setValue("标的过于集中");
    await page.get('[data-testid="reject"]').trigger("click");
    await flushPromises();

    const rejectCall = fetchMock.mock.calls.find((call) => String(call[0]).includes("/reject"));
    expect(rejectCall).toBeTruthy();
    expect(JSON.parse(String((rejectCall?.[1] as RequestInit).body))).toEqual({
      reason: "标的过于集中",
    });
    expect(page.get('[data-testid="review-status"]').text()).toContain("已驳回");
  });

  it("客户经理能看能留言，但没有放行与驳回入口", async () => {
    const page = await mountPage(ACCOUNT_MANAGER);

    expect(page.find('[data-testid="review-decision"]').exists()).toBe(false);
    expect(page.get('[data-testid="no-release-entry"]').text()).toContain("无法放行或驳回");
    expect(page.find('[data-testid="comments-panel"]').exists()).toBe(true);
  });

  it("403 时渲染无权查看而不是空白页", async () => {
    const page = await mountPage(ACCOUNT_MANAGER);
    await page.unmount();
    responded = { review: apiError(403, "该客户不在你的名下，无权查看") };

    const forbidden = await mountPage(ACCOUNT_MANAGER);
    expect(forbidden.get('[data-testid="review-forbidden"]').text()).toContain("无权查看");
  });

  it("已放行的草稿直接取顾问定稿，不再显示编辑入口", async () => {
    responded = { review: { draft_id: 7, status: "已放行" } };
    const page = await mountPage(ADVISOR);

    expect(page.get('[data-testid="final-panel"]').text()).toContain("稳健增利一号（定稿）");
    expect(page.find('[data-testid="review-decision"]').exists()).toBe(false);
  });

  it("待审状态仍是审核形态：标题与审核决定入口俱在", async () => {
    const page = await mountPage(ADVISOR);

    const header = page.get('[data-testid="page-header"]');
    expect(header.get(".page-header__title").text()).toBe("审核");
    expect(header.text()).toContain("投顾助手");
    expect(header.text()).toContain("审核");
    expect(page.get('[data-testid="back-to-queue"]').text()).toBe("返回队列");
    expect(page.find('[data-testid="review-decision"]').exists()).toBe(true);
  });

  it("已放行后页面退化为回看：标题改「查看方案」，不再有放行与驳回入口", async () => {
    responded = { review: { draft_id: 7, status: "已放行" } };
    const page = await mountPage(ADVISOR);

    const header = page.get('[data-testid="page-header"]');
    expect(header.get(".page-header__title").text()).toBe("查看方案");
    expect(header.get(".page-header__crumb-current").text()).toBe("查看方案");
    expect(page.get('[data-testid="back-to-queue"]').text()).toBe("返回投顾助手");
    expect(page.find('[data-testid="review-decision"]').exists()).toBe(false);
    expect(page.find('[data-testid="release"]').exists()).toBe(false);
    expect(page.find('[data-testid="reject"]').exists()).toBe(false);
  });

  it("已驳回后同样是回看形态：没有放行与驳回入口", async () => {
    responded = { review: { draft_id: 7, status: "已驳回" } };
    const page = await mountPage(ADVISOR);

    expect(page.get(".page-header__title").text()).toBe("查看方案");
    expect(page.find('[data-testid="review-decision"]').exists()).toBe(false);
    expect(page.find('[data-testid="release"]').exists()).toBe(false);
    expect(page.find('[data-testid="reject"]').exists()).toBe(false);
  });
});
