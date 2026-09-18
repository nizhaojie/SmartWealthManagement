// 右侧检查器的注入与塌陷：页面注入则三栏，不注入则第三栏塌成两栏。
// 形态判定只有一个来源——AppShell 看 inspector 插槽在不在，页面拿这个插槽靠 provide/inject。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.vue";
import { ADVISOR, type EmployeeRole } from "../auth/identity";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { router } from "../router";
import { stubApiFetch } from "../testing";

let pinia: Pinia;
let wrapper: VueWrapper | null = null;
let role: EmployeeRole = ADVISOR;

async function mountApp(): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/api/internal/auth/me")) {
      return { real_name: "测试员工", employee_role: role };
    }
    return undefined;
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

function hasInspector(app: VueWrapper): boolean {
  return app.classes().includes("app-shell--with-inspector");
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

describe("第三栏的注入与塌陷", () => {
  it("画像 / 投顾 / 风控 / 工单 / 数据分析注入检查器，知识库与落地页不注入", async () => {
    role = ADVISOR;
    const app = await mountApp();

    // 落地页：零注入 → 两栏
    expect(hasInspector(app)).toBe(false);

    await goTo("/profile");
    expect(hasInspector(app)).toBe(true);
    // 还没选客户时检查器给的是「等一位客户」的说明，而不是空栏。
    expect(app.get('[data-testid="inspector-empty"]').text()).toContain("还没有选中客户");

    await goTo("/advisory");
    expect(hasInspector(app)).toBe(true);

    await goTo("/risk-monitoring");
    expect(hasInspector(app)).toBe(true);
    expect(app.get('[data-testid="risk-summary-tab"]').text()).toBe("预警列表");

    await goTo("/work-orders");
    expect(hasInspector(app)).toBe(true);
    expect(app.find('[data-testid="work-order-summary-filters"]').exists()).toBe(true);

    await goTo("/knowledge");
    expect(hasInspector(app)).toBe(false);

    // 历史查询现在常驻第三栏，所以数据分析也注入检查器。
    await goTo("/data-analysis");
    expect(hasInspector(app)).toBe(true);
    expect(app.get('[data-testid="history-empty"]').text()).toContain("还没有历史查询");
  });

  it("离开注入检查器的页面后第三栏收回", async () => {
    role = ADVISOR;
    const app = await mountApp();

    await goTo("/profile");
    expect(hasInspector(app)).toBe(true);

    await goTo("/data-analysis");
    expect(hasInspector(app)).toBe(true);

    await goTo("/knowledge");
    expect(hasInspector(app)).toBe(false);
    expect(app.find(".app-shell__inspector").exists()).toBe(false);
  });
});
