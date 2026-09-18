// 角色门控：七模块 × 三角色。
//
// 断言的是三件事：不足角色渲染 ModuleForbidden；URL 与外壳（导航、登出入口）都保留；
// 角色够的时候不出现禁止页。门控只有 modules.ts 一处事实源，这里就从壳的外部钉住它。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.vue";
import { ALL_ROLES, type EmployeeRole } from "../auth/identity";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { router } from "../router";
import { stubApiFetch } from "../testing";
import { MODULES } from "./modules";

let pinia: Pinia;
let wrapper: VueWrapper | null = null;
let role: EmployeeRole = "理财顾问";

function stubIdentity(): void {
  stubApiFetch((url) => {
    if (url.includes("/api/internal/auth/me")) {
      return { real_name: "测试员工", employee_role: role };
    }
    return undefined;
  });
}

async function mountApp(): Promise<VueWrapper> {
  pinia = createPinia();
  setActivePinia(pinia);
  setTokens({ accessToken: "access-token", refreshToken: "refresh-token" });
  // 用真实的路由实例：门控在它的 beforeEach 里，另建一个 router 就把被断言的东西换掉了。
  await router.push("/");
  await router.isReady();
  wrapper = mount(App, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

/** 导航到某个模块并等 API 全部落地。 */
async function goTo(path: string): Promise<void> {
  await router.push(path);
  await flushPromises();
}

function visibleModuleKeys(): string[] {
  return MODULES.filter((module) => module.roles.includes(role)).map((module) => module.id);
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

describe("七模块 × 三角色的可见性", () => {
  for (const employeeRole of ALL_ROLES) {
    describe(employeeRole, () => {
      for (const module of MODULES) {
        const allowed = module.roles.includes(employeeRole);

        it(`${module.label}：${allowed ? "可进入" : "渲染 ModuleForbidden"}`, async () => {
          role = employeeRole;
          stubIdentity();
          const app = await mountApp();
          await goTo(module.path);

          expect(app.find('[data-testid="module-forbidden"]').exists()).toBe(!allowed);
          // 角色不足时保留自己的 URL 与外壳，不做重定向。
          expect(router.currentRoute.value.path).toBe(module.path);
          expect(app.find('button[name="logout"]').exists()).toBe(true);
          expect(app.find('button[name="nav-knowledge"]').exists()).toBe(true);
        });
      }

      it("导航只列可见模块，顶栏显示身份，登出入口恒在", async () => {
        role = employeeRole;
        stubIdentity();
        const app = await mountApp();

        for (const module of MODULES) {
          expect(app.find(`button[name="nav-${module.id}"]`).exists()).toBe(
            visibleModuleKeys().includes(module.id),
          );
        }

        expect(app.get('[data-testid="current-employee"]').text()).toContain(employeeRole);
        expect(app.find('button[name="logout"]').exists()).toBe(true);
      });
    });
  }

  it("任意角色都能从任意模块路由登出并回到登录页", async () => {
    role = "风控专员";
    stubIdentity();
    const app = await mountApp();
    await goTo("/work-orders");

    await app.get('button[name="logout"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(app.text()).toContain("员工登录");
  });
});
