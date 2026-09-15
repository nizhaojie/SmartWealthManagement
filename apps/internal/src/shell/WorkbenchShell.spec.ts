import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import ModuleView from "./ModuleView.vue";
import { MODULES } from "./modules";
import WorkbenchShell from "./WorkbenchShell.vue";

vi.mock("../auth/api", () => ({
  login: vi.fn(),
  requestLogout: vi.fn().mockResolvedValue(null),
}));

vi.mock("../knowledge/KnowledgeWorkspace.vue", () => ({
  default: { name: "KnowledgeWorkspace", template: "<div />" },
}));

vi.mock("../profile/ProfileWorkspace.vue", () => ({
  default: { name: "ProfileWorkspace", template: "<div />" },
}));

function createShellRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/",
        component: WorkbenchShell,
        children: MODULES.map((module) => ({
          path: module.path.slice(1),
          name: module.id,
          component: ModuleView,
          meta: { moduleId: module.id },
        })),
      },
    ],
  });
}

async function mountShellAt(initialPath: string, role: string, realName = "某员工") {
  currentEmployee.value = { real_name: realName, employee_role: role as never };
  const router = createShellRouter();
  await router.push(initialPath);
  await router.isReady();
  const wrapper = mount(WorkbenchShell, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

describe("WorkbenchShell", () => {
  afterEach(() => {
    currentEmployee.value = null;
  });

  it("renders a different set of visible modules per role", async () => {
    const advisorWrapper = await mountShellAt("/knowledge", ADVISOR);
    const advisorNav = advisorWrapper.find(".workbench-shell__aside").text();
    expect(advisorNav).toContain("投顾助手");
    expect(advisorNav).toContain("客户画像");
    expect(advisorNav).not.toContain("风控监测");
    expect(advisorNav).not.toContain("客户关系");

    const riskWrapper = await mountShellAt("/knowledge", RISK_OFFICER);
    const riskNav = riskWrapper.find(".workbench-shell__aside").text();
    expect(riskNav).toContain("风控监测");
    expect(riskNav).not.toContain("投顾助手");
    expect(riskNav).not.toContain("客户画像");
    expect(riskNav).not.toContain("客户关系");

    const managerWrapper = await mountShellAt("/knowledge", ACCOUNT_MANAGER);
    const managerNav = managerWrapper.find(".workbench-shell__aside").text();
    expect(managerNav).toContain("客户关系");
    expect(managerNav).not.toContain("投顾助手");
    expect(managerNav).not.toContain("客户画像");
    expect(managerNav).not.toContain("风控监测");
  });

  it("shows the logout entry point for every role on every route", async () => {
    for (const role of [ADVISOR, RISK_OFFICER, ACCOUNT_MANAGER]) {
      for (const module of MODULES) {
        const wrapper = await mountShellAt(module.path, role);
        const logoutButton = wrapper.find('button[name="logout"]');
        expect(logoutButton.exists()).toBe(true);
        wrapper.unmount();
      }
    }
  });

  it("renders the placeholder explanation with navigation and logout still present for an unimplemented module", async () => {
    const wrapper = await mountShellAt("/data-analysis", ADVISOR);

    expect(wrapper.text()).toContain("该模块尚未实现");
    expect(wrapper.find(".workbench-shell__aside").exists()).toBe(true);
    expect(wrapper.find('button[name="logout"]').exists()).toBe(true);
  });

  it("shows the current employee's name and role", async () => {
    const wrapper = await mountShellAt("/knowledge", ADVISOR, "陈顾问");

    expect(wrapper.text()).toContain("陈顾问");
    expect(wrapper.text()).toContain(ADVISOR);
  });

  it("shows a breadcrumb for the current module", async () => {
    const wrapper = await mountShellAt("/risk-monitoring", RISK_OFFICER);

    const breadcrumb = wrapper.find(".el-breadcrumb");
    expect(breadcrumb.text()).toContain("工作台");
    expect(breadcrumb.text()).toContain("风控监测");
  });

  it("returns to the previous module when the browser back button is used", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR as never };
    const router = createShellRouter();
    await router.push("/knowledge");
    await router.isReady();
    mount(WorkbenchShell, { global: { plugins: [ElementPlus, router] } });
    await flushPromises();

    await router.push("/data-analysis");
    await flushPromises();
    expect(router.currentRoute.value.path).toBe("/data-analysis");

    router.back();
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/knowledge");
  });
});
