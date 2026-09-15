import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it } from "vitest";
import { ADVISOR, RISK_OFFICER } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import ModuleView from "./ModuleView.vue";
import { MODULES } from "./modules";

async function mountModuleViewAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: MODULES.map((module) => ({
      path: module.path,
      name: module.id,
      component: ModuleView,
      meta: { moduleId: module.id },
    })),
  });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(ModuleView, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

describe("ModuleView", () => {
  afterEach(() => {
    currentEmployee.value = null;
  });

  it("renders the placeholder explanation for a module the role is allowed to see", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR };

    const wrapper = await mountModuleViewAt("/advisory");

    expect(wrapper.text()).toContain("该模块尚未实现");
    expect(wrapper.text()).toContain("投顾助手");
  });

  it("explicitly rejects a role visiting a route it has no access to, instead of hiding it", async () => {
    currentEmployee.value = { real_name: "周风控", employee_role: RISK_OFFICER };

    const wrapper = await mountModuleViewAt("/advisory");

    expect(wrapper.text()).toContain("无权访问");
    expect(wrapper.text()).not.toContain("该模块尚未实现");
  });
});
