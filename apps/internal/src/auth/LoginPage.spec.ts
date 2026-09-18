// 登录页的两条硬要求：el-form + rules 的结构契约（上一轮的坑是 el-form-item
// 套在没有 el-form 的外层），以及「登录后拿不到身份 = 登录失败」。
import ElementPlus, { ElForm, ElFormItem } from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { clearTokens, getAccessToken } from "../auth/tokenStore";
import { stubApiFetch } from "../testing";
import LoginPage from "./LoginPage.vue";

const LandingStub = { name: "LandingStub", render: () => h("div", { "data-testid": "landing" }) };

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;

beforeEach(async () => {
  localStorage.clear();
  clearTokens();
  pinia = createPinia();
  setActivePinia(pinia);
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/login", name: "login", component: LoginPage },
      { path: "/", name: "landing", component: LandingStub },
    ],
  });
  await router.push("/login");
  await router.isReady();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
  clearTokens();
});

function mountPage(): VueWrapper {
  wrapper = mount(LoginPage, { global: { plugins: [pinia, ElementPlus, router] } });
  return wrapper;
}

async function submit(page: VueWrapper): Promise<void> {
  await page.find("form").trigger("submit.prevent");
  await flushPromises();
}

describe("员工登录页", () => {
  it("每个表单项都在带 rules 的 el-form 之内", () => {
    const page = mountPage();
    const form = page.findComponent(ElForm);

    expect(page.text()).toContain("员工登录");
    expect(page.find("form.el-form").exists()).toBe(true);
    // 两个字段都必须在 form 之内：游离的 el-form-item 既不校验也不报错。
    expect(page.findAll("form.el-form .el-form-item")).toHaveLength(2);
    expect(page.findAllComponents(ElFormItem)).toHaveLength(2);
    expect(form.props("rules")).toMatchObject({
      username: [{ required: true }],
      password: [{ required: true }],
    });
  });

  it("换到令牌并拿到身份之后才进工作台", async () => {
    stubApiFetch((url) => {
      if (url.includes("/api/internal/auth/login")) {
        return { access_token: "access-token", refresh_token: "refresh-token" };
      }
      if (url.includes("/api/internal/auth/me")) {
        return { real_name: "张顾问", employee_role: "理财顾问" };
      }
      return undefined;
    });

    const page = mountPage();
    await page.find('input[name="username"]').setValue("zhang");
    await page.find('input[name="password"]').setValue("Test@1234");
    await submit(page);

    expect(router.currentRoute.value.path).toBe("/");
    expect(getAccessToken()).toBe("access-token");
  });

  it("拿不到员工身份时算登录失败：给内联提示并清掉令牌", async () => {
    stubApiFetch((url) => {
      if (url.includes("/api/internal/auth/login")) {
        return { access_token: "access-token", refresh_token: "refresh-token" };
      }
      if (url.includes("/api/internal/auth/me")) {
        return null;
      }
      return undefined;
    });

    const page = mountPage();
    await page.find('input[name="username"]').setValue("zhang");
    await page.find('input[name="password"]').setValue("Test@1234");
    await submit(page);

    expect(router.currentRoute.value.path).toBe("/login");
    expect(page.find('[data-testid="login-error"]').exists()).toBe(true);
    expect(getAccessToken()).toBeNull();
    expect(document.querySelector(".el-message")).toBeNull();
  });
});
