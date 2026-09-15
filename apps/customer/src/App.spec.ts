import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";
import { login as loginRequest, logout as logoutRequest } from "./auth/api";
import { clearTokens } from "./auth/tokenStore";

vi.mock("./auth/api", () => ({
  login: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("./api/health", () => ({
  fetchHealth: vi.fn().mockResolvedValue({
    status: "ok",
    llm_provider: "fake",
    dependencies: {},
  }),
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
  });

  it("directs to the login page when not authenticated", () => {
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });

    expect(wrapper.text()).toContain("客户登录");
    expect(wrapper.text()).not.toContain("系统健康状态");
  });

  it("shows the protected content after a successful login", async () => {
    vi.mocked(loginRequest).mockResolvedValue({
      access_token: "access-token",
      refresh_token: "refresh-token",
    });
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });

    await submitLogin(wrapper, "wangc1", "Test@1234");

    expect(wrapper.text()).toContain("系统健康状态");
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

    await wrapper.find("button").trigger("click");
    await flushPromises();

    expect(logoutRequest).toHaveBeenCalled();
    expect(wrapper.text()).toContain("客户登录");
  });
});
