import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";
import { login as loginRequest } from "./auth/api";
import { clearTokens } from "./auth/tokenStore";

vi.mock("./auth/api", () => ({
  login: vi.fn(),
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
  });

  it("directs to the login page when not authenticated", () => {
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });

    expect(wrapper.text()).toContain("员工登录");
    expect(wrapper.text()).not.toContain("内部工作台");
  });

  it("shows the workbench shell after a successful login", async () => {
    vi.mocked(loginRequest).mockResolvedValue({
      access_token: "access-token",
      refresh_token: "refresh-token",
    });
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });

    await submitLogin(wrapper, "advisor1", "Test@1234");

    expect(wrapper.text()).toContain("内部工作台");
  });

  it("shows an inline error instead of throwing when login fails", async () => {
    vi.mocked(loginRequest).mockRejectedValue(new Error("invalid credentials"));
    const wrapper = mount(App, { global: { plugins: [ElementPlus] } });

    await submitLogin(wrapper, "advisor1", "wrong-password");

    expect(wrapper.text()).toContain("账号或密码错误");
    expect(wrapper.text()).toContain("员工登录");
  });
});
