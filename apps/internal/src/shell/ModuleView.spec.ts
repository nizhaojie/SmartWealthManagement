import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import ModuleView from "./ModuleView.vue";
import { MODULES } from "./modules";

const { listCustomers, getCustomerProfile, listRiskAssessments } = vi.hoisted(() => ({
  listCustomers: vi.fn(),
  getCustomerProfile: vi.fn(),
  listRiskAssessments: vi.fn(),
}));

vi.mock("../profile/api", () => ({
  listCustomers,
  getCustomerProfile,
  listRiskAssessments,
  writeProfileTag: vi.fn(),
}));

vi.mock("../analytics/api", () => ({
  runAnalyticsQuery: vi.fn(),
  listAnalyticsHistory: vi.fn().mockResolvedValue([]),
  listAnalyticsExamples: vi.fn().mockResolvedValue([]),
}));

vi.mock("../advisory/api", () => ({
  getQueue: vi.fn().mockResolvedValue({ pending_requests: [], pending_reviews: [] }),
  getMyHistory: vi.fn().mockResolvedValue([]),
  listCustomersForPlan: vi.fn().mockResolvedValue([]),
  generatePlan: vi.fn(),
}));

vi.mock("../risk/api", () => ({
  listAlerts: vi.fn().mockResolvedValue([]),
  listWorkOrders: vi.fn().mockResolvedValue([]),
  listRiskRules: vi.fn().mockResolvedValue([]),
  setRiskRuleEnabled: vi.fn(),
  getAlert: vi.fn(),
  getWorkOrder: vi.fn(),
  excludeAlert: vi.fn(),
  escalateAlert: vi.fn(),
  deriveWorkOrder: vi.fn(),
  acceptWorkOrder: vi.fn(),
  completeWorkOrder: vi.fn(),
  closeWorkOrder: vi.fn(),
}));

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
  beforeEach(() => {
    listCustomers.mockReset();
    getCustomerProfile.mockReset();
    listRiskAssessments.mockReset();
    listCustomers.mockResolvedValue([]);
    listRiskAssessments.mockResolvedValue([]);
  });

  afterEach(() => {
    currentEmployee.value = null;
  });

  it("renders the placeholder explanation for a module the role is allowed to see", async () => {
    currentEmployee.value = { real_name: "刘经理", employee_role: ACCOUNT_MANAGER };

    const wrapper = await mountModuleViewAt("/customer-relations");

    expect(wrapper.text()).toContain("该模块尚未实现");
    expect(wrapper.text()).toContain("客户关系");
  });

  it("opens the risk monitoring workspace on its own route", async () => {
    currentEmployee.value = { real_name: "周风控", employee_role: RISK_OFFICER };

    const wrapper = await mountModuleViewAt("/risk-monitoring");

    expect(wrapper.text()).not.toContain("该模块尚未实现");
    expect(wrapper.text()).toContain("预警列表");
  });

  it("opens the data analysis workspace on its own route", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR };

    const wrapper = await mountModuleViewAt("/data-analysis");

    expect(wrapper.text()).not.toContain("该模块尚未实现");
    expect(wrapper.text()).toContain("历史查询");
  });

  it("opens the customer profile workspace on its own route", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR };

    const wrapper = await mountModuleViewAt("/profile");

    expect(wrapper.text()).toContain("选择一位客户查看画像");
    expect(wrapper.text()).not.toContain("该模块尚未实现");
  });

  it("opens the advisory workspace on its own route", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR };

    const wrapper = await mountModuleViewAt("/advisory");

    expect(wrapper.text()).not.toContain("该模块尚未实现");
    expect(wrapper.text()).toContain("待生成的方案请求");
  });

  it("explicitly rejects a role visiting a route it has no access to, instead of hiding it", async () => {
    currentEmployee.value = { real_name: "周风控", employee_role: RISK_OFFICER };

    const advisory = await mountModuleViewAt("/advisory");
    expect(advisory.text()).toContain("无权访问");
    expect(advisory.text()).not.toContain("该模块尚未实现");

    const profile = await mountModuleViewAt("/profile");
    expect(profile.text()).toContain("无权访问");
    expect(profile.text()).not.toContain("选择一位客户查看画像");
  });
});
