// 侧栏底部的「今日风险预警」小卡三个角色都可见；N=0 给空态文案而不是隐藏，
// 加载失败给「暂不可用」——它是壳层对 GET /api/internal/risk-alerts 的一次额外调用。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import App from "../App.vue";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { routes } from "../router";
import { stubApiFetch } from "../testing";

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;

function alertRow(id: number) {
  return {
    id,
    customer_id: 1,
    customer_name: "王客户",
    alert_type: "大额转账",
    alert_level: "重度",
    confidence: 0.9,
    rule_codes: ["R001"],
    rule_count: 1,
    transaction_ids: [],
    status: "未处理",
    created_at: "2026-09-18T10:00:00",
    work_order_id: null,
    work_order_status: null,
  };
}

async function mountApp(responder: (url: string) => unknown): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/api/internal/auth/me")) {
      return { real_name: "李风控", employee_role: "风控专员" };
    }
    return responder(url);
  });

  pinia = createPinia();
  setActivePinia(pinia);
  setTokens({ accessToken: "access-token", refreshToken: "refresh-token" });
  router = createRouter({ history: createMemoryHistory(), routes });
  await router.push("/");
  await router.isReady();
  wrapper = mount(App, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  localStorage.clear();
  clearTokens();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
  clearTokens();
});

describe("今日风险预警小卡", () => {
  it("有未处理预警时显示待处置条数", async () => {
    const app = await mountApp((url) =>
      url.includes("/api/internal/risk-alerts") ? [alertRow(1), alertRow(2)] : undefined,
    );

    expect(app.get('[data-testid="today-risk-alerts-count"]').text()).toBe("2");
    expect(app.get('[data-testid="today-risk-alerts"]').text()).toContain("条待处置");
  });

  it("N=0 时给空态文案，而不是把卡片藏起来", async () => {
    const app = await mountApp((url) =>
      url.includes("/api/internal/risk-alerts") ? [] : undefined,
    );

    expect(app.find('[data-testid="today-risk-alerts"]').exists()).toBe(true);
    expect(app.get('[data-testid="today-risk-alerts-empty"]').text()).toContain(
      "今日没有待处置的预警",
    );
  });

  it("加载失败时显示暂不可用", async () => {
    const app = await mountApp((url) => {
      if (url.includes("/api/internal/risk-alerts")) {
        throw new Error("network down");
      }
      return undefined;
    });

    expect(app.get('[data-testid="today-risk-alerts-unavailable"]').text()).toBe("暂不可用");
  });
});
