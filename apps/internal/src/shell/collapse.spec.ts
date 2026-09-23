// 检查器开关 + 侧栏折叠 footer：开关只在页面注入检查器时出现，点击折叠第三栏、
// 再点恢复；折叠态下 footer 小卡渲染图标 + 角标（N=0 不显示角标、失败仅图标）。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.vue";
import { ADVISOR, type EmployeeRole } from "../auth/identity";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { router } from "../router";
import { stubApiFetch } from "../testing";

const SIDEBAR_KEY = "wealth-internal-sidebar-collapsed";

let pinia: Pinia;
let wrapper: VueWrapper | null = null;
let role: EmployeeRole = ADVISOR;

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

/** 列表接口的一页（ADR-0024）。 */
function alertPage(rows: unknown[], total = rows.length) {
  return { items: rows, total, page: 1, page_size: 1 };
}

async function mountApp(responder?: (url: string) => unknown): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/api/internal/auth/me")) {
      return { real_name: "测试员工", employee_role: role };
    }
    return responder?.(url);
  });

  pinia = createPinia();
  setActivePinia(pinia);
  setTokens({ accessToken: "access-token", refreshToken: "refresh-token" });
  await router.push("/");
  await router.isReady();
  wrapper = mount(App, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

async function goTo(path: string): Promise<void> {
  await router.push(path);
  await flushPromises();
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

describe("检查器开关", () => {
  it("仅在有检查器的页面出现", async () => {
    role = ADVISOR;
    const app = await mountApp();

    // 落地页：零注入 → 无开关
    expect(app.find('[data-testid="inspector-toggle"]').exists()).toBe(false);

    await goTo("/profile");
    expect(app.find('[data-testid="inspector-toggle"]').exists()).toBe(true);

    await goTo("/knowledge");
    expect(app.find('[data-testid="inspector-toggle"]').exists()).toBe(false);
  });

  it("点击后第三栏消失、再点击恢复", async () => {
    role = ADVISOR;
    const app = await mountApp();
    await goTo("/profile");

    expect(app.find(".app-shell__inspector").exists()).toBe(true);
    expect(app.classes()).not.toContain("app-shell--inspector-collapsed");

    await app.get('[data-testid="inspector-toggle"]').trigger("click");
    expect(app.find(".app-shell__inspector").exists()).toBe(false);
    expect(app.classes()).toContain("app-shell--inspector-collapsed");

    await app.get('[data-testid="inspector-toggle"]').trigger("click");
    expect(app.find(".app-shell__inspector").exists()).toBe(true);
    expect(app.classes()).not.toContain("app-shell--inspector-collapsed");
  });
});

describe("侧栏折叠下的 footer 小卡", () => {
  it("有未处理预警时渲染图标 + 角标", async () => {
    localStorage.setItem(SIDEBAR_KEY, "true");
    role = ADVISOR;
    const app = await mountApp((url) =>
      url.includes("/api/internal/risk-alerts")
        ? alertPage([alertRow(1)], 2)
        : undefined,
    );

    expect(app.find('[data-testid="today-risk-alerts-icon"]').exists()).toBe(true);
    expect(app.get('[data-testid="today-risk-alerts-count"]').text()).toBe("2");
    // 折叠态不渲染展开态的空态/计数文案
    expect(app.find('[data-testid="today-risk-alerts-empty"]').exists()).toBe(false);
    expect(app.find('[data-testid="today-risk-alerts-unavailable"]').exists()).toBe(false);
  });

  it("N=0 时不显示角标", async () => {
    localStorage.setItem(SIDEBAR_KEY, "true");
    role = ADVISOR;
    const app = await mountApp((url) =>
      url.includes("/api/internal/risk-alerts") ? alertPage([]) : undefined,
    );

    expect(app.find('[data-testid="today-risk-alerts-icon"]').exists()).toBe(true);
    expect(app.find('[data-testid="today-risk-alerts-count"]').exists()).toBe(false);
  });

  it("失败态仅图标", async () => {
    localStorage.setItem(SIDEBAR_KEY, "true");
    role = ADVISOR;
    const app = await mountApp((url) => {
      if (url.includes("/api/internal/risk-alerts")) {
        throw new Error("network down");
      }
      return undefined;
    });

    expect(app.find('[data-testid="today-risk-alerts-icon"]').exists()).toBe(true);
    expect(app.find('[data-testid="today-risk-alerts-count"]').exists()).toBe(false);
  });
});
