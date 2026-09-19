// 顾问回看自己决定过的内容：历史表每行都能点回审核页，放行与驳回记录一视同仁。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { stubApiFetch } from "../testing";
import AdvisoryWorkspace from "./AdvisoryWorkspace.vue";

const HISTORY = [
  {
    draft_id: 7,
    customer_id: 9,
    customer_name: "王小明",
    action: "放行",
    reason: null,
    decided_at: "2026-09-18T11:00:00",
  },
  {
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

async function mountWorkspace(history: unknown = HISTORY): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/api/internal/advisory/history")) return { history };
    return undefined;
  });

  pinia = createPinia();
  setActivePinia(pinia);

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/advisory", name: "advisory", component: AdvisoryWorkspace },
      { path: "/advisory/reviews/:draftId", name: "advisory-review", component: { template: "<div />" } },
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
