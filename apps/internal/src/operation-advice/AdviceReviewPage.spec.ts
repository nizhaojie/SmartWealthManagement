// 操作建议的审核页：载荷只有「一个产品、一个方向、一个金额、一条理由」，不渲染方案
// 特有的字段；放行 / 驳回只对理财顾问开放；已决定后退化为只读回看。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ACCOUNT_MANAGER, ADVISOR, type EmployeeRole } from "../auth/identity";
import { useAuthStore } from "../stores/auth";
import { apiError, requestedUrls, stubApiFetch } from "../testing";
import AdviceReviewPage from "./AdviceReviewPage.vue";

const ADVICE = {
  id: 21,
  customer_id: 9,
  manager_id: 4,
  product_code: "F000001",
  product_name: "稳健增利一号",
  direction: "申购",
  amount: "200000.00",
  reason: "客户现金持仓偏高，且这只产品的期限与他的流动性安排一致。",
  content_classification: "投顾内容",
  generated_at: "2026-09-18T09:00:00",
  disclaimer: "本内容为投顾内容，须经审核后送达。",
};

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;
let responded: { review?: unknown; advice?: unknown } = {};

async function mountPage(role: EmployeeRole): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/operation-advice/21/review")) {
      return responded.review ?? { advice_id: 21, status: "待审" };
    }
    if (url.includes("/operation-advice/21/comments")) return { comments: [] };
    if (url.includes("/operation-advice/21/release")) return { id: 21, status: "已放行" };
    if (url.includes("/operation-advice/21/reject")) {
      return { id: 21, status: "已驳回", reason: "金额与客户流动性不符" };
    }
    if (url.includes("/operation-advice/21")) return responded.advice ?? ADVICE;
    return undefined;
  });

  pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().currentEmployee = { real_name: "测试员工", employee_role: role };

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/advisory/operation-advice/:adviceId",
        name: "operation-advice-review",
        component: AdviceReviewPage,
      },
      { path: "/advisory", name: "advisory", component: { template: "<div />" } },
      { path: "/customer-relations", name: "customer-relations", component: { template: "<div />" } },
    ],
  });
  await router.push("/advisory/operation-advice/21");
  await router.isReady();

  wrapper = mount(AdviceReviewPage, { global: { plugins: [pinia, ElementPlus, router] } });
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

describe("操作建议的审核页", () => {
  it("渲染建议本体的四件事：产品、方向、金额、理由", async () => {
    const page = await mountPage(ADVISOR);

    expect(page.get('[data-testid="advice-product"]').text()).toContain("稳健增利一号");
    expect(page.get('[data-testid="advice-direction"]').text()).toContain("申购");
    expect(page.get('[data-testid="advice-amount"]').text()).toContain("200,000.00");
    expect(page.get('[data-testid="advice-reason"]').text()).toContain("流动性安排");
    expect(page.get('[data-testid="advice-review-status"]').text()).toContain("待审");
    expect(page.get('[data-testid="advice-review-type"]').text()).toContain("操作建议");
  });

  it("不渲染方案特有的字段：候选池、配置建议、画像警示一个都不出现", async () => {
    // 后端不会给这些字段。这里刻意塞进去：边界一旦破了（例如复用方案的渲染件），
    // 它们会以空值或原值的形式出现，而那种页面看起来仍然是「正常」的。
    responded = {
      advice: {
        ...ADVICE,
        candidates: [{ product_name: "方案特有标记-候选" }],
        allocation_suggestion: { "方案特有标记-配置": 60 },
        warnings: [{ code: "W1", message: "方案特有标记-警示" }],
        candidate_pool_snapshot: { note: "方案特有标记-快照" },
      },
    };
    const page = await mountPage(ADVISOR);

    // 方案审核页的三个渲染面（AI 原稿 / 顾问编辑版本 / 顾问定稿）在这里都不存在。
    expect(page.find('[data-testid="original-panel"]').exists()).toBe(false);
    expect(page.find('[data-testid="edited-panel"]').exists()).toBe(false);
    expect(page.find('[data-testid="final-panel"]').exists()).toBe(false);
    expect(page.find('[data-testid="allocation-input"]').exists()).toBe(false);

    expect(page.text()).not.toContain("方案特有标记");
    // 建议本体的四件事照常渲染——不渲染方案字段不等于什么都不渲染。
    expect(page.get('[data-testid="advice-product"]').text()).toContain("稳健增利一号");
  });

  it("理财顾问能放行，放行后页面退化为只读", async () => {
    const page = await mountPage(ADVISOR);

    await page.get('[data-testid="release"]').trigger("click");
    await flushPromises();

    expect(page.get('[data-testid="advice-review-status"]').text()).toContain("已放行");
    expect(page.find('[data-testid="review-decision"]').exists()).toBe(false);
    // 原稿就是送达版本（#06 的放行不产生第二份载荷），因此载荷仍然在。
    expect(page.get('[data-testid="advice-product"]').text()).toContain("稳健增利一号");
  });

  it("驳回理由为空时提交不出去", async () => {
    const page = await mountPage(ADVISOR);
    const fetchMock = vi.mocked(globalThis.fetch);

    expect(page.get('[data-testid="reject"]').attributes("disabled")).toBeDefined();
    await page.get('[data-testid="reject"]').trigger("click");
    await flushPromises();

    expect(requestedUrls(fetchMock, "/reject")).toHaveLength(0);
  });

  it("已驳回的内容同样是只读回看", async () => {
    responded = { review: { advice_id: 21, status: "已驳回" } };
    const page = await mountPage(ADVISOR);

    expect(page.get(".page-header__title").text()).toBe("查看操作建议");
    expect(page.find('[data-testid="release"]').exists()).toBe(false);
    expect(page.find('[data-testid="reject"]').exists()).toBe(false);
  });

  it("客户经理读得到、留言得了，但没有放行与驳回入口", async () => {
    const page = await mountPage(ACCOUNT_MANAGER);
    const fetchMock = vi.mocked(globalThis.fetch);

    expect(page.get('[data-testid="advice-product"]').text()).toContain("稳健增利一号");
    expect(page.find('[data-testid="review-decision"]').exists()).toBe(false);
    expect(page.get('[data-testid="no-release-entry"]').text()).toContain("无法放行或驳回");
    expect(page.find('[data-testid="comments-panel"]').exists()).toBe(true);

    await page.get('[data-testid="comment-input"]').setValue("金额能不能再小一点？");
    await page.get('[data-testid="post-comment"]').trigger("click");
    await flushPromises();

    const posted = fetchMock.mock.calls.find(
      (call) => String(call[0]).includes("/comments") && (call[1] as RequestInit)?.method === "POST",
    );
    expect(posted).toBeTruthy();
    expect(JSON.parse(String((posted?.[1] as RequestInit).body))).toEqual({
      body: "金额能不能再小一点？",
    });
  });

  it("客户经理返回时回到自己的模块，而不是顾问的队列", async () => {
    const page = await mountPage(ACCOUNT_MANAGER);

    expect(page.get('[data-testid="back-from-advice-review"]').text()).toBe("返回客户关系");
  });

  it("403 时渲染无权查看而不是空白页", async () => {
    responded = { review: apiError(403, "该客户不在你的名下，无权查看") };
    const page = await mountPage(ACCOUNT_MANAGER);

    expect(page.get('[data-testid="advice-review-forbidden"]').text()).toContain("无权查看");
  });
});
