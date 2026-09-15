import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";
import { login as loginRequest, logout as logoutRequest } from "./auth/api";
import { clearTokens } from "./auth/tokenStore";
import { getAssets, listTransactions } from "./assets/api";
import { getCurrentAssessment } from "./risk-assessment/api";

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

async function submitLogin(wrapper: ReturnType<typeof mount>, username: string, password: string) {
  await wrapper.find('input[name="username"]').setValue(username);
  await wrapper.find('input[name="password"]').setValue(password);
  await wrapper.find("form").trigger("submit.prevent");
  await flushPromises();
}

describe("App", () => {
  beforeEach(() => {
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
  });

  it("directs to the login page when not authenticated", () => {
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });

    expect(wrapper.text()).toContain("客户登录");
    expect(wrapper.find('input[name="chat-message"]').exists()).toBe(false);
  });

  it("shows the protected chat page after a successful login", async () => {
    vi.mocked(loginRequest).mockResolvedValue({
      access_token: "access-token",
      refresh_token: "refresh-token",
    });
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });

    await submitLogin(wrapper, "wangc1", "Test@1234");

    expect(wrapper.find('input[name="chat-message"]').exists()).toBe(true);
  });

  it("shows an inline error instead of throwing when login fails", async () => {
    vi.mocked(loginRequest).mockRejectedValue(new Error("invalid credentials"));
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });

    await submitLogin(wrapper, "wangc1", "wrong-password");

    expect(wrapper.text()).toContain("账号或密码错误");
    expect(wrapper.text()).toContain("客户登录");
  });

  it("returns to the login page after logging out", async () => {
    vi.mocked(loginRequest).mockResolvedValue({
      access_token: "access-token",
      refresh_token: "refresh-token",
    });
    vi.mocked(logoutRequest).mockResolvedValue(null);
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });
    await submitLogin(wrapper, "wangc1", "Test@1234");

    await wrapper.get('button[name="logout"]').trigger("click");
    await flushPromises();

    expect(logoutRequest).toHaveBeenCalled();
    expect(wrapper.text()).toContain("客户登录");
  });

  it("opens the risk assessment result from customer navigation", async () => {
    vi.mocked(loginRequest).mockResolvedValue({
      access_token: "access-token",
      refresh_token: "refresh-token",
    });
    vi.mocked(getCurrentAssessment).mockResolvedValue({
      risk_level: "C1",
      valid_until: "2027-03-15",
    });
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });
    await submitLogin(wrapper, "wangc1", "Test@1234");

    await wrapper.get('button[name="nav-risk-assessment"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("保守型");
    expect(wrapper.text()).toContain("2027-03-15");
    expect(wrapper.text()).not.toContain("置信度");
  });

  it("opens product screening from customer navigation", async () => {
    vi.mocked(loginRequest).mockResolvedValue({
      access_token: "access-token",
      refresh_token: "refresh-token",
    });
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });
    await submitLogin(wrapper, "wangc1", "Test@1234");

    await wrapper.get('button[name="nav-products"]').trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("这是符合条件的产品清单，不是推荐");
    expect(wrapper.text()).toContain("请顾问出具方案");
  });

  it("opens the assets page from customer navigation", async () => {
    vi.mocked(loginRequest).mockResolvedValue({
      access_token: "access-token",
      refresh_token: "refresh-token",
    });
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });
    await submitLogin(wrapper, "wangc1", "Test@1234");

    await wrapper.get('button[name="nav-assets"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="total-market-value"]').text()).toBe("20420.00");
    expect(wrapper.get('[data-testid="holding-count"]').text()).toBe("1");
    expect(wrapper.get('[data-testid="risk-level"]').text()).toContain("C1");
  });
});
