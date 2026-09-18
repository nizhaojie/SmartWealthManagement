// 工单流转的角色门控与字段要求：接单只需理由，办结还要结论，关闭只需理由；
// 非风控专员只看到一句说明，终态不再给入口。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ACCOUNT_MANAGER, RISK_OFFICER, type EmployeeRole } from "../auth/identity";
import { useAuthStore } from "../stores/auth";
import { stubApiFetch } from "../testing";
import WorkOrderDetailPage from "./WorkOrderDetailPage.vue";

function workOrder(overrides: Record<string, unknown> = {}) {
  return {
    id: 5,
    work_order_no: "WO20260918001",
    order_type: "预警处置",
    sub_type: null,
    alert_id: 3,
    customer_id: 9,
    handler_id: null,
    handler_name: "",
    status: "待处理",
    current_node: "待处理",
    priority: "紧急",
    biz_content: null,
    handle_reason: null,
    handle_result: null,
    created_at: "2026-09-18T10:00:00",
    updated_at: "2026-09-18T10:00:00",
    transitions: [],
    ...overrides,
  };
}

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;

async function mountPage(role: EmployeeRole, detail = workOrder()): Promise<VueWrapper> {
  stubApiFetch((url) => (url.includes("/api/internal/work-orders/5") ? detail : undefined));

  pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().currentEmployee = { real_name: "测试员工", employee_role: role };

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/work-orders/:workOrderId", name: "work-order-detail", component: WorkOrderDetailPage },
      { path: "/work-orders", name: "work-orders", component: { template: "<div />" } },
    ],
  });
  await router.push("/work-orders/5");
  await router.isReady();

  wrapper = mount(WorkOrderDetailPage, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("工单详情与流转", () => {
  it("风控专员在待处理工单上只能接单，理由为空时点不动", async () => {
    const page = await mountPage(RISK_OFFICER);

    expect(page.find('[data-testid="work-order-actions"]').exists()).toBe(true);
    expect(page.get('[data-testid="accept"]').attributes("disabled")).toBeDefined();
    expect(page.find('[data-testid="complete"]').exists()).toBe(false);

    await page.get('[data-testid="transition-reason"]').setValue("开始核实");
    expect(page.get('[data-testid="accept"]').attributes("disabled")).toBeUndefined();
  });

  it("处理中工单要同时填理由与结论才能办结，关闭只要理由", async () => {
    const page = await mountPage(RISK_OFFICER, workOrder({ status: "处理中", handler_name: "李风控" }));

    expect(page.get('[data-testid="complete"]').attributes("disabled")).toBeDefined();
    expect(page.get('[data-testid="close"]').attributes("disabled")).toBeDefined();

    await page.get('[data-testid="transition-reason"]').setValue("已核实");
    expect(page.get('[data-testid="close"]').attributes("disabled")).toBeUndefined();
    expect(page.get('[data-testid="complete"]').attributes("disabled")).toBeDefined();

    await page.get('[data-testid="transition-conclusion"]').setValue("确认误报，已归档");
    expect(page.get('[data-testid="complete"]').attributes("disabled")).toBeUndefined();
  });

  it("客户经理看不到流转表单", async () => {
    const page = await mountPage(ACCOUNT_MANAGER);

    expect(page.find('[data-testid="work-order-actions"]').exists()).toBe(false);
    expect(page.get('[data-testid="read-only-hint"]').text()).toContain("由风控专员完成");
  });

  it("终态工单不再给流转入口", async () => {
    const page = await mountPage(RISK_OFFICER, workOrder({ status: "已完成" }));

    expect(page.find('[data-testid="work-order-actions"]').exists()).toBe(false);
    expect(page.get('[data-testid="terminal-hint"]').text()).toContain("不能再流转");
  });

  it("流转留痕把「建单」这一跳也画出来", async () => {
    const page = await mountPage(
      RISK_OFFICER,
      workOrder({
        status: "处理中",
        transitions: [
          {
            from_status: null,
            to_status: "待处理",
            handler_id: 4,
            handler_name: "李风控",
            reason: "由预警派生",
            handled_at: "2026-09-18T10:05:00",
          },
        ],
      }),
    );

    const table = page.get('[data-testid="transitions-table"]');
    expect(table.text()).toContain("建单 → 待处理");
    expect(table.text()).toContain("由预警派生");
  });
});
