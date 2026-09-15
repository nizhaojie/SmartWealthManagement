import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";
import { login as loginRequest, requestLogout } from "./auth/api";
import { fetchCurrentEmployee } from "./auth/identity";
import { clearTokens } from "./auth/tokenStore";
import { router } from "./router";

vi.mock("./auth/api", () => ({
  login: vi.fn(),
  requestLogout: vi.fn().mockResolvedValue(null),
}));

vi.mock("./auth/identity", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./auth/identity")>()),
  fetchCurrentEmployee: vi.fn(),
}));

async function submitLogin(wrapper: ReturnType<typeof mount>, username: string, password: string) {
  await wrapper.find('input[name="username"]').setValue(username);
  await wrapper.find('input[name="password"]').setValue(password);
  await wrapper.find("form").trigger("submit.prevent");
  await flushPromises();
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
    vi.mocked(fetchCurrentEmployee).mockReset();
    vi.mocked(requestLogout).mockReset().mockResolvedValue(null);
    await router.push("/login");
    await router.isReady();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("directs to the login page when not authenticated, even for a deep link", async () => {
    await router.push("/knowledge");
    const wrapper = mountApp();
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(wrapper.text()).toContain("员工登录");
  });

  it("shows the workbench shell with the employee's identity after a successful login", async () => {
    vi.mocked(loginRequest).mockResolvedValue({ access_token: "access-token", refresh_token: "refresh-token" });
    vi.mocked(fetchCurrentEmployee).mockResolvedValue({ real_name: "陈顾问", employee_role: "理财顾问" });
    const wrapper = mountApp();

    await submitLogin(wrapper, "advisor1", "Test@1234");

    expect(router.currentRoute.value.path).toBe("/knowledge");
    expect(wrapper.text()).toContain("陈顾问");
    expect(wrapper.text()).toContain("理财顾问");
  });

  it("shows an inline error instead of throwing when login fails", async () => {
    vi.mocked(loginRequest).mockRejectedValue(new Error("invalid credentials"));
    const wrapper = mountApp();

    await submitLogin(wrapper, "advisor1", "wrong-password");

    expect(wrapper.text()).toContain("账号或密码错误");
    expect(wrapper.text()).toContain("员工登录");
  });

  it("returns to the login page once the session's credentials become invalid", async () => {
    vi.mocked(loginRequest).mockResolvedValue({ access_token: "access-token", refresh_token: "refresh-token" });
    vi.mocked(fetchCurrentEmployee).mockResolvedValue({ real_name: "陈顾问", employee_role: "理财顾问" });
    const wrapper = mountApp();
    await submitLogin(wrapper, "advisor1", "Test@1234");
    expect(router.currentRoute.value.path).toBe("/knowledge");

    clearTokens();
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
  });

  it("logs out from any route and returns to the login page", async () => {
    vi.mocked(loginRequest).mockResolvedValue({ access_token: "access-token", refresh_token: "refresh-token" });
    vi.mocked(fetchCurrentEmployee).mockResolvedValue({ real_name: "周风控", employee_role: "风控专员" });
    const wrapper = mountApp();
    await submitLogin(wrapper, "risk1", "Test@1234");
    await router.push("/risk-monitoring");
    await flushPromises();

    await wrapper.find('button[name="logout"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(wrapper.text()).toContain("员工登录");
  });
});
