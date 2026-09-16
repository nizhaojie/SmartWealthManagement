import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@wealth/shared";
import { ACCOUNT_MANAGER, ADVISOR } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import type { AdvisoryCandidate, AdvisoryComment, AdvisoryDraft, AdvisoryReviewStatus } from "./types";

const { getDraft, getReviewStatus, getFinal, listComments, postComment, releaseDraft, rejectDraft } =
  vi.hoisted(() => ({
    getDraft: vi.fn(),
    getReviewStatus: vi.fn(),
    getFinal: vi.fn(),
    listComments: vi.fn(),
    postComment: vi.fn(),
    releaseDraft: vi.fn(),
    rejectDraft: vi.fn(),
  }));

vi.mock("./api", () => ({
  getDraft,
  getReviewStatus,
  getFinal,
  listComments,
  postComment,
  releaseDraft,
  rejectDraft,
}));

import AdvisoryReviewPage from "./AdvisoryReviewPage.vue";

function makeCandidate(overrides: Partial<AdvisoryCandidate> = {}): AdvisoryCandidate {
  return {
    product_code: "F000001",
    product_name: "稳健增利债券基金",
    product_type: "债券基金",
    risk_level: "C1",
    expected_return: "3.20",
    term_days: 90,
    composite_score: 0.82,
    score_breakdown: [
      { dimension: "收益", raw_value: "3.20%", score: 0.8, weight: 0.33, contribution: 0.26 },
      { dimension: "风险", raw_value: "C1", score: 1, weight: 0.33, contribution: 0.33 },
      { dimension: "期限匹配度", raw_value: "90天", score: 1, weight: 0.34, contribution: 0.34 },
    ],
    reason: "客户风险承受等级为 C1，本产品风险等级 C1 与其完全匹配",
    ...overrides,
  };
}

function makeDraft(overrides: Partial<AdvisoryDraft> = {}): AdvisoryDraft {
  return {
    id: 42,
    customer_id: 7,
    advisor_id: 1,
    tilt: "均衡",
    content_classification: "投顾内容",
    candidates: [makeCandidate(), makeCandidate({ product_code: "F000002", product_name: "货币增利基金" })],
    allocation_suggestion: { 股票: 40, 债券: 35, 现金: 15, 另类: 10 },
    warnings: [{ code: "PROFILE_STALE", message: "客户画像距上次计算已超过 180 天" }],
    profile_computed_at: "2026-09-01T09:00:00",
    candidate_pool_snapshot: {},
    generated_at: "2026-09-16T09:00:00",
    advisory_request_id: null,
    disclaimer: "本方案不构成任何直接投资建议",
    ...overrides,
  };
}

function makeReview(status: AdvisoryReviewStatus["status"] = "待审"): AdvisoryReviewStatus {
  return { draft_id: 42, status };
}

function makeComment(overrides: Partial<AdvisoryComment> = {}): AdvisoryComment {
  return {
    id: 1,
    review_id: 1,
    author_id: 2,
    author_name: "刘经理",
    author_role: "客户经理",
    body: "客户询问进度",
    created_at: "2026-09-16T10:00:00",
    ...overrides,
  };
}

function makeRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/advisory", name: "advisory", component: { template: "<div />" } },
      {
        path: "/advisory/reviews/:draftId",
        name: "advisory-review",
        component: AdvisoryReviewPage,
      },
    ],
  });
  return router;
}

async function mountReviewPage(draftId = "42") {
  const router = makeRouter();
  await router.push(`/advisory/reviews/${draftId}`);
  await router.isReady();
  const wrapper = mount(AdvisoryReviewPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return { wrapper, router };
}

describe("AdvisoryReviewPage", () => {
  beforeEach(() => {
    getDraft.mockReset();
    getReviewStatus.mockReset();
    getFinal.mockReset();
    listComments.mockReset();
    postComment.mockReset();
    releaseDraft.mockReset();
    rejectDraft.mockReset();

    getDraft.mockResolvedValue(makeDraft());
    getReviewStatus.mockResolvedValue(makeReview());
    listComments.mockResolvedValue([makeComment()]);

    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR as never };
  });

  afterEach(() => {
    currentEmployee.value = null;
  });

  it("renders the AI draft and the editable copy side by side", async () => {
    const { wrapper } = await mountReviewPage();

    const original = wrapper.get('[data-test="original-panel"]');
    const edited = wrapper.get('[data-test="edited-panel"]');
    expect(original.text()).toContain("稳健增利债券基金");
    expect(edited.text()).toContain("稳健增利债券基金");
    expect(original.text()).toContain("AI 原稿");
    expect(edited.text()).toContain("编辑版本");
  });

  it("expands to show each dimension's contribution to the ranking", async () => {
    const { wrapper } = await mountReviewPage();

    const expandIcons = wrapper.findAll(".el-table__expand-icon");
    await expandIcons[0].trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("贡献 0.26");
  });

  it("shows release and reject entry points for an advisor, reject disabled until a reason is filled", async () => {
    const { wrapper } = await mountReviewPage();

    expect(wrapper.find('[data-test="release"]').exists()).toBe(true);
    const rejectButton = wrapper.get('[data-test="reject"]');
    expect(rejectButton.attributes("aria-disabled")).toBe("true");

    await wrapper.get('[data-test="reject-reason"]').setValue("理由不充分");
    await flushPromises();

    expect(wrapper.get('[data-test="reject"]').attributes("aria-disabled")).toBe("false");
  });

  it("submitting a reject with a reason calls the API and updates the status", async () => {
    rejectDraft.mockResolvedValue({ draft_id: 42, status: "已驳回", reason: "理由不充分" });
    const { wrapper } = await mountReviewPage();

    await wrapper.get('[data-test="reject-reason"]').setValue("理由不充分");
    await wrapper.get('[data-test="reject"]').trigger("click");
    await flushPromises();

    expect(rejectDraft).toHaveBeenCalledWith(42, "理由不充分");
    expect(wrapper.get('[data-test="review-status"]').text()).toContain("已驳回");
  });

  it("hides the release entry point for an account manager", async () => {
    currentEmployee.value = { real_name: "刘经理", employee_role: ACCOUNT_MANAGER as never };
    const { wrapper } = await mountReviewPage();

    expect(wrapper.find('[data-test="release"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="no-release-entry"]').exists()).toBe(true);
  });

  it("renders a forbidden state when the backend refuses access", async () => {
    getDraft.mockRejectedValue(new ApiError({ code: 403, message: "无权查看", data: null, trace_id: "t1" }));
    const { wrapper } = await mountReviewPage();

    expect(wrapper.find('[data-test="forbidden"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="original-panel"]').exists()).toBe(false);
  });

  it("renders and can post comments, visible to both roles", async () => {
    postComment.mockResolvedValue(makeComment({ id: 2, body: "已跟客户沟通" }));
    const { wrapper } = await mountReviewPage();

    expect(wrapper.text()).toContain("客户询问进度");

    await wrapper.get('[data-test="comment-input"]').setValue("已跟客户沟通");
    await wrapper.get('[data-test="post-comment"]').trigger("click");
    await flushPromises();

    expect(postComment).toHaveBeenCalledWith(42, "已跟客户沟通");
    expect(wrapper.text()).toContain("已跟客户沟通");
  });

  it("renders the profile warning carried by the draft", async () => {
    const { wrapper } = await mountReviewPage();

    expect(wrapper.text()).toContain("客户画像距上次计算已超过 180 天");
  });

  it("has an independent route with a back-to-queue button", async () => {
    const { wrapper, router } = await mountReviewPage();

    await wrapper.get('[data-test="back-to-queue"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory");
  });
});
