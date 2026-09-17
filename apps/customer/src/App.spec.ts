import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import App from "./App.vue";
import { login as loginRequest, logout as logoutRequest } from "./auth/api";
import { clearTokens } from "./auth/tokenStore";
import { getAssets, listTransactions } from "./assets/api";
import { getCurrentAssessment } from "./risk-assessment/api";
import { router, routes } from "./router";

vi.mock("./auth/api", () => ({
  login: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("./assets/api", () => ({
  getAssets: vi.fn(),
  listTransactions: vi.fn(),
}));

vi.mock("./risk-assessment/api", () => ({
  getCurrentAssessment: vi.fn(),
  getQuestionnaire: vi.fn(),
  saveDraft: vi.fn(),
  submitAssessment: vi.fn(),
}));

vi.mock("./products/api", () => ({
  listProducts: vi.fn().mockResolvedValue({ products: [] }),
  getProduct: vi.fn(),
}));

async function submitLogin(wrapper: VueWrapper, username: string, password: string) {
  await wrapper.find('input[name="username"]').setValue(username);
  await wrapper.find('input[name="password"]').setValue(password);
  await wrapper.find("form").trigger("submit.prevent");
  await flushPromises();
}

function mockSuccessfulLogin() {
  vi.mocked(loginRequest).mockResolvedValue({
    access_token: "access-token",
    refresh_token: "refresh-token",
  });
}

let activeWrapper: VueWrapper | null = null;

function mountApp(): VueWrapper {
  activeWrapper = mount(App, { global: { plugins: [ElementPlus, router] } }) as VueWrapper;
  return activeWrapper;
}

describe("App", () => {
  beforeEach(async () => {
    clearTokens();
    vi.mocked(loginRequest).mockReset();
    vi.mocked(logoutRequest).mockReset();
    vi.mocked(getCurrentAssessment).mockReset();
    vi.mocked(getAssets).mockReset();
    vi.mocked(listTransactions).mockReset();
    vi.mocked(getAssets).mockResolvedValue({
      risk_level: "C1",
      risk_level_valid_until: "2027-03-15",
      total_market_value: "20420.00",
      holding_count: 1,
      holdings: [],
    });
    vi.mocked(listTransactions).mockResolvedValue({ transactions: [] });
    await router.push("/login");
    await router.isReady();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("directs to the login page when not authenticated, even for a deep link", async () => {
    await router.push("/products");
    const wrapper = mountApp();
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(wrapper.text()).toContain("客户登录");
    expect(wrapper.find('input[name="chat-message"]').exists()).toBe(false);
  });

  it("shows the chat view at /chat after a successful login", async () => {
    mockSuccessfulLogin();
    const wrapper = mountApp();

    await submitLogin(wrapper, "wangc1", "Test@1234");

    expect(router.currentRoute.value.path).toBe("/chat");
    expect(wrapper.find('input[name="chat-message"]').exists()).toBe(true);
  });

  it("shows an inline error instead of throwing when login fails", async () => {
    vi.mocked(loginRequest).mockRejectedValue(new Error("invalid credentials"));
    const wrapper = mountApp();

    await submitLogin(wrapper, "wangc1", "wrong-password");

    expect(wrapper.text()).toContain("账号或密码错误");
    expect(wrapper.text()).toContain("客户登录");
  });

  it("returns to the login page after logging out", async () => {
    mockSuccessfulLogin();
    vi.mocked(logoutRequest).mockResolvedValue(null);
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");

    await wrapper.get('button[name="logout"]').trigger("click");
    await flushPromises();

    expect(logoutRequest).toHaveBeenCalled();
    expect(router.currentRoute.value.path).toBe("/login");
    expect(wrapper.text()).toContain("客户登录");
  });

  it("renders each view at its own URL", async () => {
    mockSuccessfulLogin();
    vi.mocked(getCurrentAssessment).mockResolvedValue({
      risk_level: "C1",
      valid_until: "2027-03-15",
    });
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");

    await router.push("/risk-assessment");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/risk-assessment");
    expect(wrapper.text()).toContain("保守型");

    await router.push("/products");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/products");
    expect(wrapper.text()).toContain("这是符合条件的产品清单，不是推荐");

    await router.push("/assets");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/assets");
    expect(wrapper.get('[data-testid="total-market-value"]').text()).toBe("20420.00");

    await router.push("/chat");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/chat");
    expect(wrapper.find('input[name="chat-message"]').exists()).toBe(true);
  });

  it("keeps the view after a refresh-style remount at the same URL", async () => {
    mockSuccessfulLogin();
    const first = mountApp();
    await submitLogin(first, "wangc1", "Test@1234");
    await router.push("/products");
    await flushPromises();
    first.unmount();

    const remounted = mountApp();
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/products");
    expect(remounted.text()).toContain("这是符合条件的产品清单，不是推荐");
  });

  it("navigates to each view URL from the shell nav", async () => {
    mockSuccessfulLogin();
    vi.mocked(getCurrentAssessment).mockResolvedValue({
      risk_level: "C1",
      valid_until: "2027-03-15",
    });
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");

    for (const name of ["risk-assessment", "products", "assets", "chat"] as const) {
      await wrapper.get(`button[name="nav-${name}"]`).trigger("click");
      await flushPromises();
      expect(router.currentRoute.value.path).toBe(`/${name}`);
    }
  });

  it("returns to the previous view with the browser back button", async () => {
    // jsdom 不投递真实 history 遍历的 popstate，后退行为本身由 vue-router 负责，
    // 这里用同一份路由表 + memory history 验证路由表下的后退语义。
    mockSuccessfulLogin();
    const testRouter = createRouter({ history: createMemoryHistory(), routes });
    await testRouter.push("/login");
    await testRouter.isReady();
    const wrapper = mount(App, { global: { plugins: [ElementPlus, testRouter] } });
    await submitLogin(wrapper, "wangc1", "Test@1234");
    expect(testRouter.currentRoute.value.path).toBe("/chat");

    await testRouter.push("/assets");
    await flushPromises();
    expect(testRouter.currentRoute.value.path).toBe("/assets");

    testRouter.back();
    await flushPromises();
    expect(testRouter.currentRoute.value.path).toBe("/chat");
    wrapper.unmount();
  });
});
