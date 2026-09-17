import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@wealth/shared";
import { ADVISOR, RISK_OFFICER } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import type { AlertSummary, RiskRule, WorkOrder } from "./types";

const { listAlerts, listWorkOrders, listRiskRules, setRiskRuleEnabled } = vi.hoisted(() => ({
  listAlerts: vi.fn(),
  listWorkOrders: vi.fn(),
  listRiskRules: vi.fn(),
  setRiskRuleEnabled: vi.fn(),
}));

vi.mock("./api", () => ({
  listAlerts,
  listWorkOrders,
  listRiskRules,
  setRiskRuleEnabled,
}));

import RiskMonitoringWorkspace from "./RiskMonitoringWorkspace.vue";

function makeAlert(overrides: Partial<AlertSummary> = {}): AlertSummary {
  return {
    id: 1,
    customer_id: 11,
    customer_name: "王守成",
    alert_type: "大额交易",
    alert_level: "轻度",
    confidence: 0.1,
    rule_codes: ["R001"],
    rule_count: 1,
    transaction_ids: [1],
    status: "未处理",
    created_at: "2026-09-17T09:00:00",
    work_order_id: null,
    work_order_status: null,
    ...overrides,
  };
}

function makeWorkOrder(overrides: Partial<WorkOrder> = {}): WorkOrder {
  return {
    id: 7,
    work_order_no: "WO20260917093000ABCDEF",
    order_type: "预警处置",
    sub_type: null,
    alert_id: 2,
    customer_id: 12,
    handler_id: 4,
    handler_name: "周风控",
    status: "待处理",
    current_node: "待处理",
    priority: "特急",
    biz_content: null,
    handle_reason: "金额与实际收入不匹配",
    handle_result: null,
    created_at: "2026-09-17T09:30:00",
    updated_at: "2026-09-17T09:30:00",
    ...overrides,
  };
}

function makeRule(overrides: Partial<RiskRule> = {}): RiskRule {
  return {
    id: 4,
    rule_code: "R001",
    rule_name: "单笔大额交易",
    category: "大额交易",
    description: "单笔交易金额达到大额交易申报阈值",
    field: "amount",
    field_label: "交易金额",
    operator: "gte",
    operator_label: "大于等于",
    threshold: { value: "50000" },
    threshold_text: "50000",
    window_hours: null,
    alert_level: "轻度",
    weight: 1,
    enabled: true,
    ...overrides,
  };
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/risk-monitoring",
        name: "risk-monitoring",
        component: { template: "<div />" },
      },
      {
        path: "/risk-monitoring/alerts/:alertId",
        name: "risk-alert-detail",
        component: { template: "<div />" },
      },
      {
        path: "/risk-monitoring/work-orders/:workOrderId",
        name: "risk-work-order-detail",
        component: { template: "<div />" },
      },
    ],
  });
}

async function mountWorkspace() {
  const router = makeRouter();
  await router.push("/risk-monitoring");
  await router.isReady();
  const wrapper = mount(RiskMonitoringWorkspace, {
    global: { plugins: [ElementPlus, router] },
  });
  await flushPromises();
  return { wrapper, router };
}

describe("RiskMonitoringWorkspace", () => {
  beforeEach(() => {
    listAlerts.mockReset().mockResolvedValue([]);
    listWorkOrders.mockReset().mockResolvedValue([]);
    listRiskRules.mockReset().mockResolvedValue([]);
    setRiskRuleEnabled.mockReset();
    currentEmployee.value = { real_name: "周风控", employee_role: RISK_OFFICER };
  });

  afterEach(() => {
    currentEmployee.value = null;
  });

  it("renders each alert with the facts needed to decide what to read first", async () => {
    listAlerts.mockResolvedValue([
      makeAlert({
        id: 3,
        customer_name: "李思远",
        alert_level: "重度",
        alert_type: "快进快出",
        confidence: 0.9,
        rule_codes: ["R001", "R012"],
        rule_count: 2,
        work_order_status: "处理中",
      }),
    ]);

    const { wrapper } = await mountWorkspace();
    const text = wrapper.text();

    expect(text).toContain("李思远");
    expect(text).toContain("重度");
    expect(text).toContain("0.90");
    expect(text).toContain("R001、R012");
    expect(text).toContain("处理中");
  });

  it("re-queries the backend when a level filter is picked, and renders the filtered set", async () => {
    const light = makeAlert({ id: 1, customer_name: "王守成", alert_level: "轻度" });
    const severe = makeAlert({ id: 2, customer_name: "李思远", alert_level: "重度" });
    listAlerts.mockImplementation((filters: { alertLevel?: string } = {}) =>
      Promise.resolve(filters.alertLevel === "重度" ? [severe] : [light, severe]),
    );
    const { wrapper } = await mountWorkspace();
    expect(wrapper.text()).toContain("王守成");

    const [levelSelect] = wrapper
      .get('[data-test="alert-filters"]')
      .findAllComponents({ name: "ElSelect" });
    await levelSelect.setValue("重度");
    await flushPromises();

    expect(listAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ alertLevel: "重度" }));
    expect(wrapper.text()).toContain("李思远");
    expect(wrapper.text()).not.toContain("王守成");
  });

  it("re-queries the backend when a status filter is picked", async () => {
    const { wrapper } = await mountWorkspace();

    const [, statusSelect] = wrapper
      .get('[data-test="alert-filters"]')
      .findAllComponents({ name: "ElSelect" });
    await statusSelect.setValue("已排除");
    await flushPromises();

    expect(listAlerts).toHaveBeenLastCalledWith(expect.objectContaining({ status: "已排除" }));
  });

  it("offers a time range filter alongside the level and status ones", async () => {
    const { wrapper } = await mountWorkspace();

    const range = wrapper.get('[data-test="alert-date-range"]');

    expect(range.findAll("input.el-range-input").length).toBe(2);
    expect(range.html()).toContain("开始日期");
    expect(range.html()).toContain("结束日期");
  });

  it("reorders the rendered alerts when sorting by confidence", async () => {
    listAlerts.mockResolvedValue([
      makeAlert({ id: 1, customer_name: "王守成", confidence: 0.1 }),
      makeAlert({ id: 2, customer_name: "李思远", confidence: 0.9 }),
    ]);
    const { wrapper } = await mountWorkspace();
    expect(wrapper.text().indexOf("王守成")).toBeLessThan(wrapper.text().indexOf("李思远"));

    const [, , sortSelect] = wrapper
      .get('[data-test="alert-filters"]')
      .findAllComponents({ name: "ElSelect" });
    await sortSelect.setValue("confidence_desc");
    await flushPromises();

    const text = wrapper.text();
    expect(text.indexOf("李思远")).toBeLessThan(text.indexOf("王守成"));
  });

  it("renders an empty state instead of an empty table when there are no alerts", async () => {
    const { wrapper } = await mountWorkspace();

    expect(wrapper.get('[data-test="alerts-empty"]').text()).toContain("暂无预警");
    expect(wrapper.find('[data-test="alerts-table"]').exists()).toBe(false);
  });

  it("shows the backend's message when the alert list cannot be loaded", async () => {
    listAlerts.mockRejectedValue(
      new ApiError({ code: 500, message: "服务内部错误", data: null, trace_id: "" }),
    );

    const { wrapper } = await mountWorkspace();

    expect(wrapper.get('[data-test="alert-error"]').text()).toContain("服务内部错误");
  });

  it("lists work orders with their status and filters them by status", async () => {
    listWorkOrders.mockResolvedValue([makeWorkOrder({ status: "已完成", handler_name: "周风控" })]);
    const { wrapper } = await mountWorkspace();

    const table = wrapper.get('[data-test="work-orders-table"]').text();
    expect(table).toContain("WO20260917093000ABCDEF");
    expect(table).toContain("已完成");
    expect(table).toContain("周风控");

    const [statusSelect] = wrapper
      .get('[data-test="work-order-filters"]')
      .findAllComponents({ name: "ElSelect" });
    await statusSelect.setValue("待处理");
    await flushPromises();

    expect(listWorkOrders).toHaveBeenLastCalledWith({ status: "待处理" });
  });

  it("renders an empty state when no work order has been created yet", async () => {
    const { wrapper } = await mountWorkspace();

    expect(wrapper.get('[data-test="work-orders-empty"]').text()).toContain("暂无工单");
  });

  it("reflects a transitioned status the next time the list is shown", async () => {
    // 流转发生在别的页面上，而列表每次都向服务端要当前状态——不缓存，就不存在
    // 「办完了列表还显示处理中」这种要刷新才对的假象。
    listWorkOrders.mockResolvedValue([makeWorkOrder({ status: "处理中" })]);
    const { wrapper } = await mountWorkspace();
    expect(wrapper.get('[data-test="work-order-status"]').text()).toContain("处理中");

    listWorkOrders.mockResolvedValue([makeWorkOrder({ status: "已完成" })]);
    wrapper.unmount();
    const { wrapper: reloaded } = await mountWorkspace();

    expect(reloaded.get('[data-test="work-order-status"]').text()).toContain("已完成");
  });

  it("lists the rules with their judgement and lets a risk officer switch one off", async () => {
    listRiskRules.mockResolvedValue([makeRule()]);
    setRiskRuleEnabled.mockResolvedValue(makeRule({ enabled: false }));
    const { wrapper } = await mountWorkspace();

    expect(wrapper.get('[data-test="rules-table"]').text()).toContain("单笔大额交易");
    expect(wrapper.get('[data-test="rules-table"]').text()).toContain("交易金额");

    const [toggle] = wrapper.findAllComponents({ name: "ElSwitch" });
    await toggle.vm.$emit("change", false);
    await flushPromises();

    expect(setRiskRuleEnabled).toHaveBeenCalledWith(4, false);
    expect(wrapper.get('[data-test="rules-table"]').text()).toContain("单笔大额交易");
  });

  it("keeps the rule switches read-only for a role that cannot change them", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR };
    listRiskRules.mockResolvedValue([makeRule()]);
    const { wrapper } = await mountWorkspace();

    const [toggle] = wrapper.findAllComponents({ name: "ElSwitch" });
    expect(toggle.props("disabled")).toBe(true);
  });

  it("opens an alert on its own URL so the link can be shared", async () => {
    listAlerts.mockResolvedValue([makeAlert({ id: 42 })]);
    const { wrapper, router } = await mountWorkspace();

    await wrapper.get('[data-test="open-alert"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("risk-alert-detail");
    expect(router.currentRoute.value.params.alertId).toBe("42");
  });

  it("opens a work order's handling page on its own URL", async () => {
    listWorkOrders.mockResolvedValue([makeWorkOrder({ id: 7 })]);
    const { wrapper, router } = await mountWorkspace();

    await wrapper.get('[data-test="open-work-order"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("risk-work-order-detail");
    expect(router.currentRoute.value.params.workOrderId).toBe("7");
  });
});
