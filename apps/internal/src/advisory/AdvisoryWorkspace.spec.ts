import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AdvisoryDraft, AdvisoryHistoryEntry, AdvisoryQueue, CustomerOption } from "./types";

const { getQueue, getMyHistory, generatePlan, listCustomersForPlan } = vi.hoisted(() => ({
  getQueue: vi.fn(),
  getMyHistory: vi.fn(),
  generatePlan: vi.fn(),
  listCustomersForPlan: vi.fn(),
}));

vi.mock("./api", () => ({ getQueue, getMyHistory, generatePlan, listCustomersForPlan }));

import AdvisoryWorkspace from "./AdvisoryWorkspace.vue";

function makeQueue(overrides: Partial<AdvisoryQueue> = {}): AdvisoryQueue {
  return {
    pending_requests: [
      {
        id: 11,
        request_no: "AR2026091600001",
        customer_id: 1,
        customer_name: "王守成",
        filters: { product_type: "债券基金" },
        submitted_at: "2026-09-16T09:00:00",
        waiting_seconds: 3600,
      },
    ],
    pending_reviews: [
      {
        draft_id: 21,
        customer_id: 2,
        customer_name: "李思远",
        status: "待审",
        tilt: "均衡",
        generated_at: "2026-09-16T10:00:00",
        waiting_seconds: 120,
      },
    ],
    ...overrides,
  };
}

function makeHistory(): AdvisoryHistoryEntry[] {
  return [
    {
      draft_id: 30,
      customer_id: 3,
      customer_name: "张衡",
      action: "放行",
      reason: null,
      decided_at: "2026-09-15T08:00:00",
    },
  ];
}

function makeDraft(overrides: Partial<AdvisoryDraft> = {}): AdvisoryDraft {
  return {
    id: 99,
    customer_id: 1,
    advisor_id: 1,
    tilt: "均衡",
    content_classification: "投顾内容",
    candidates: [],
    allocation_suggestion: {},
    warnings: [],
    profile_computed_at: "2026-09-16T08:00:00",
    candidate_pool_snapshot: {},
    generated_at: "2026-09-16T09:00:00",
    advisory_request_id: 11,
    disclaimer: "本方案不构成任何直接投资建议",
    ...overrides,
  };
}

function makeCustomers(): CustomerOption[] {
  return [
    { id: 1, real_name: "王守成" },
    { id: 2, real_name: "李思远" },
  ];
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/advisory", name: "advisory", component: { template: "<div />" } },
      {
        path: "/advisory/reviews/:draftId",
        name: "advisory-review",
        component: { template: "<div />" },
      },
    ],
  });
}

async function mountWorkspace() {
  const router = makeRouter();
  await router.push("/advisory");
  await router.isReady();
  const wrapper = mount(AdvisoryWorkspace, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return { wrapper, router };
}

describe("AdvisoryWorkspace", () => {
  beforeEach(() => {
    getQueue.mockReset();
    getMyHistory.mockReset();
    generatePlan.mockReset();
    listCustomersForPlan.mockReset();
    getQueue.mockResolvedValue(makeQueue());
    getMyHistory.mockResolvedValue(makeHistory());
    listCustomersForPlan.mockResolvedValue(makeCustomers());
  });

  it("shows pending customer requests and pending reviews with their waiting time", async () => {
    const { wrapper } = await mountWorkspace();

    const text = wrapper.text();
    expect(text).toContain("王守成");
    expect(text).toContain("1 小时 0 分钟");
    expect(text).toContain("李思远");
    expect(text).toContain("2 分钟");
  });

  it("shows the advisor's own review history", async () => {
    const { wrapper } = await mountWorkspace();

    expect(wrapper.text()).toContain("张衡");
    expect(wrapper.text()).toContain("放行");
  });

  it("generating a plan from a pending request navigates to its review page", async () => {
    generatePlan.mockResolvedValue(makeDraft());
    const { wrapper, router } = await mountWorkspace();

    await wrapper.get('[data-test="open-generate"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-test="confirm-generate"]').trigger("click");
    await flushPromises();

    expect(generatePlan).toHaveBeenCalledWith(
      expect.objectContaining({ customerId: 1, advisoryRequestId: 11 }),
    );
    expect(router.currentRoute.value.name).toBe("advisory-review");
    expect(router.currentRoute.value.params.draftId).toBe("99");
  });

  it("opening a pending review navigates to its review page", async () => {
    const { wrapper, router } = await mountWorkspace();

    await wrapper.get('[data-test="open-review"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("advisory-review");
    expect(router.currentRoute.value.params.draftId).toBe("21");
  });

  it("lets the advisor generate a plan for any customer without a pending request", async () => {
    generatePlan.mockResolvedValue(makeDraft({ advisory_request_id: null }));
    const { wrapper, router } = await mountWorkspace();

    const customerSelect = wrapper.getComponent({ name: "ElSelect" });
    await customerSelect.setValue(2);
    await wrapper.get('[data-test="open-direct-generate"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-test="confirm-generate"]').trigger("click");
    await flushPromises();

    expect(generatePlan).toHaveBeenCalledWith(
      expect.objectContaining({ customerId: 2, advisoryRequestId: null }),
    );
    expect(router.currentRoute.value.name).toBe("advisory-review");
  });
});
