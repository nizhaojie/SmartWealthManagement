// 登录页的两条硬要求：el-form + rules 的结构契约（上一轮的坑是 el-form-item
// 套在没有 el-form 的外层），以及失败给内联提示而不是 toast。
//
// 这里不断言「空表单不会调到登录接口」：vitest 默认把 element-plus 外部化、交给 Node 加载，
// 而 Node 对 async-validator（CJS，只写了 exports.default）的默认导入拿到的是对象而非构造函数，
// ElForm.validate() 于是静默放行。浏览器与构建产物里 Vite 走 module 字段（dist-web 的 ESM
// 默认导出），校验正常。要在测试里覆盖这条路径，需要把 element-plus 内联进测试模块图。
import ElementPlus, { ElForm, ElFormItem } from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ApiError } from "@wealth/shared";
import LoginPage from "./LoginPage.vue";

const { loginRequest, logoutRequest } = vi.hoisted(() => ({
  loginRequest: vi.fn(),
  logoutRequest: vi.fn(),
}));

vi.mock("./api", () => ({ login: loginRequest, logout: logoutRequest }));

const ChatStub = {
  name: "ChatStub",
  render: () => h("div", { "data-testid": "chat-view" }),
};

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;

beforeEach(async () => {
  pinia = createPinia();
  setActivePinia(pinia);
  loginRequest.mockReset();
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/login", name: "login", component: LoginPage },
      { path: "/chat", name: "chat", component: ChatStub },
    ],
  });
  await router.push("/login");
  await router.isReady();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

function mountPage(): VueWrapper {
  wrapper = mount(LoginPage, { global: { plugins: [pinia, ElementPlus, router] } });
  return wrapper;
}

describe("LoginPage", () => {
  it("shows the brand and keeps every form item inside one el-form carrying rules", () => {
    const page = mountPage();
    const form = page.findComponent(ElForm);

    expect(page.text()).toContain("智能财富管家");
    expect(page.find("form.el-form").exists()).toBe(true);
    // 两个字段都必须在 form 之内：游离的 el-form-item 既不校验也不报错。
    expect(page.findAll("form.el-form .el-form-item")).toHaveLength(2);
    expect(page.findAllComponents(ElFormItem)).toHaveLength(2);
    expect(form.props("rules")).toMatchObject({
      username: [{ required: true }],
      password: [{ required: true }],
    });
    expect(page.find('input[name="username"]').exists()).toBe(true);
    expect(page.find('input[name="password"]').exists()).toBe(true);
  });

  it("reports a rejected login inline instead of as a toast", async () => {
    loginRequest.mockRejectedValue(
      new ApiError({ code: 401, message: "账号或密码错误", data: null, trace_id: "" }),
    );
    const page = mountPage();

    await page.find('input[name="username"]').setValue("wangc1");
    await page.find('input[name="password"]').setValue("wrong-password");
    await page.find("form").trigger("submit.prevent");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(page.get('[data-testid="login-error"]').text()).toBe("账号或密码错误");
    expect(document.querySelector(".el-message")).toBeNull();
  });
});
