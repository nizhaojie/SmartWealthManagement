import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@wealth/shared";
import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import type { AlertDetail, WorkOrder } from "./types";

const { getAlert, excludeAlert, escalateAlert, deriveWorkOrder } = vi.hoisted(() => ({
  getAlert: vi.fn(),
  excludeAlert: vi.fn(),
  escalateAlert: vi.fn(),
  deriveWorkOrder: vi.fn(),
}));

vi.mock("./api", () => ({ getAlert, excludeAlert, escalateAlert, deriveWorkOrder }));

import AlertDetailPage from "./AlertDetailPage.vue";

function makeWorkOrder(overrides: Partial<WorkOrder> = {}): WorkOrder {
  return {
    id: 7,
    work_order_no: "WO20260917093000ABCDEF",
    order_type: "预警处置",
    sub_type: null,
    alert_id: 12,
    customer_id: 11,
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

function makeDetail(overrides: Partial<AlertDetail> = {}): AlertDetail {
  return {
    id: 12,
    customer_id: 11,
    customer_name: "王守成",
    alert_type: "大额交易",
    alert_level: "中度",
    confidence: 0.8,
    rule_codes: ["R001", "R003"],
    rule_hits: [
      {
        rule_code: "R001",
        rule_name: "单笔大额交易",
        category: "大额交易",
        alert_level: "轻度",
        weight: 1,
        field: "amount",
        field_label: "交易金额",
        operator: "gte",
        operator_label: "大于等于",
        operator_symbol: "≥",
        threshold: "50000",
        observed_value: "520000",
        evidence: "交易金额 520000 ≥ 阈值 50000",
      },
      {
        rule_code: "R003",
        rule_name: "同日累计大额交易",
        category: "大额交易",
        alert_level: "中度",
        weight: 2,
        field: "amount",
        field_label: "交易金额",
        operator: "daily_sum_gte",
        operator_label: "同日求和",
        operator_symbol: "≥",
        threshold: "200000",
        observed_value: "520000",
        evidence: "同日交易金额合计 520000 ≥ 阈值 200000",
      },
    ],
    transaction_ids: [31],
    trigger_detail: "单笔大额交易（R001）：交易金额 520000 ≥ 阈值 50000",
    status: "未处理",
    handler_id: null,
    handle_result: null,
    handled_by_name: "",
    created_at: "2026-09-17T09:00:00",
    customer: {
      customer_id: 11,
      real_name: "王守成",
      customer_level: "普通",
      risk_level: "C1",
      manager_name: "刘经理",
    },
    transactions: [
      {
        id: 31,
        transaction_no: "TX20260917090000ABCDEF",
        customer_id: 11,
        product_id: 1,
        product_code: "F000001",
        product_name: "天枢货币基金",
        transaction_type: "申购",
        amount: "520000.00",
        shares: "520000",
        nav: "1.000000",
        fee: "0.00",
        status: "已确认",
        occurred_at: "2026-09-17T09:00:00",
      },
    ],
    customer_history: [
      {
        id: 9,
        alert_type: "频繁交易",
        alert_level: "轻度",
        confidence: 0.15,
        rule_codes: ["R007"],
        status: "已排除",
        created_at: "2026-09-01T10:00:00",
      },
    ],
    work_order: null,
    ...overrides,
  };
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/risk-monitoring", name: "risk-monitoring", component: { template: "<div />" } },
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

async function mountDetailPage(alertId = "12") {
  const router = makeRouter();
  await router.push(`/risk-monitoring/alerts/${alertId}`);
  await router.isReady();
  const wrapper = mount(AlertDetailPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return { wrapper, router };
}

describe("AlertDetailPage", () => {
  beforeEach(() => {
    getAlert.mockReset().mockResolvedValue(makeDetail());
    excludeAlert.mockReset().mockResolvedValue(makeDetail());
    escalateAlert.mockReset().mockResolvedValue(makeDetail());
    deriveWorkOrder.mockReset().mockResolvedValue({ id: 7 });
    currentEmployee.value = { real_name: "周风控", employee_role: RISK_OFFICER };
  });

  afterEach(() => {
    currentEmployee.value = null;
  });

  it("shows every hit down to the field, the observed value and the threshold", async () => {
    const { wrapper } = await mountDetailPage();

    const table = wrapper.get('[data-test="rule-hits-table"]').text();
    expect(table).toContain("单笔大额交易（R001）");
    expect(table).toContain("交易金额");
    expect(table).toContain("520000");
    expect(table).toContain("≥ 50000");
    expect(table).toContain("交易金额 520000 ≥ 阈值 50000");

    // 聚合类命中要能看出这个数是从哪个窗口来的，否则专员无法判断它是不是误报。
    expect(table).toContain("同日交易金额合计 520000 ≥ 阈值 200000");
  });

  it("falls back to the stored text when a legacy alert carries no structured hits", async () => {
    getAlert.mockResolvedValue(makeDetail({ rule_hits: [] }));

    const { wrapper } = await mountDetailPage();

    expect(wrapper.find('[data-test="rule-hits-table"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="trigger-detail"]').text()).toContain(
      "交易金额 520000 ≥ 阈值 50000",
    );
  });

  it("carries the related transaction and the customer facts without leaving the page", async () => {
    const { wrapper } = await mountDetailPage();

    const transactions = wrapper.get('[data-test="transactions-table"]').text();
    expect(transactions).toContain("TX20260917090000ABCDEF");
    expect(transactions).toContain("天枢货币基金");
    expect(transactions).toContain("520000.00");

    const customer = wrapper.get('[data-test="customer-card"]').text();
    expect(customer).toContain("王守成");
    expect(customer).toContain("C1");
    expect(customer).toContain("刘经理");
  });

  it("shows the confidence, marked as display-only", async () => {
    const { wrapper } = await mountDetailPage();

    expect(wrapper.get('[data-test="alert-confidence"]').text()).toContain("0.80");
  });

  it("lists this customer's earlier alerts", async () => {
    const { wrapper } = await mountDetailPage();

    const history = wrapper.get('[data-test="history-table"]').text();
    expect(history).toContain("频繁交易");
    expect(history).toContain("已排除");
    expect(history).toContain("R007");
  });

  it("says so when this customer has no earlier alerts", async () => {
    getAlert.mockResolvedValue(makeDetail({ customer_history: [] }));

    const { wrapper } = await mountDetailPage();

    expect(wrapper.get('[data-test="history-empty"]').text()).toContain("没有其他预警记录");
    expect(wrapper.find('[data-test="history-table"]').exists()).toBe(false);
  });

  it("refuses to submit a disposition while the reason is empty", async () => {
    const { wrapper } = await mountDetailPage();

    expect(wrapper.get('[data-test="exclude-alert"]').attributes("aria-disabled")).toBe("true");
    expect(wrapper.get('[data-test="escalate-alert"]').attributes("aria-disabled")).toBe("true");
    expect(wrapper.get('[data-test="derive-work-order"]').attributes("aria-disabled")).toBe("true");

    await wrapper.get('[data-test="exclude-alert"]').trigger("click");
    await flushPromises();
    expect(excludeAlert).not.toHaveBeenCalled();

    await wrapper.get('[data-test="disposition-reason"]').setValue("客户资金来源为工资卡，误报");
    await flushPromises();

    expect(wrapper.get('[data-test="exclude-alert"]').attributes("aria-disabled")).toBe("false");
    await wrapper.get('[data-test="exclude-alert"]').trigger("click");
    await flushPromises();

    expect(excludeAlert).toHaveBeenCalledWith(12, "客户资金来源为工资卡，误报");
  });

  it("escalates with the reason and shows who handled it afterwards", async () => {
    let current = makeDetail();
    getAlert.mockImplementation(() => Promise.resolve(current));
    const { wrapper } = await mountDetailPage();

    await wrapper.get('[data-test="disposition-reason"]').setValue("超出我的处置权限");
    current = makeDetail({
      status: "已升级",
      handled_by_name: "周风控",
      handle_result: "超出我的处置权限",
    });
    await wrapper.get('[data-test="escalate-alert"]').trigger("click");
    await flushPromises();

    expect(escalateAlert).toHaveBeenCalledWith(12, "超出我的处置权限");
    expect(getAlert).toHaveBeenCalledTimes(2);
    expect(wrapper.get('[data-test="handled-by"]').text()).toContain("周风控");
  });

  it("derives a work order from the alert, then points at it instead of offering the entry point again", async () => {
    let current = makeDetail();
    getAlert.mockImplementation(() => Promise.resolve(current));
    const { wrapper } = await mountDetailPage();

    await wrapper.get('[data-test="disposition-reason"]').setValue("金额与实际收入不匹配");
    // 派生之后详情重新读一次，预警行上就挂上了那张工单。
    current = makeDetail({ work_order: makeWorkOrder() });
    await wrapper.get('[data-test="derive-work-order"]').trigger("click");
    await flushPromises();

    expect(deriveWorkOrder).toHaveBeenCalledWith(12, "金额与实际收入不匹配");
    expect(wrapper.get('[data-test="work-order-link"]').text()).toContain(
      "WO20260917093000ABCDEF",
    );
    expect(wrapper.get('[data-test="derive-work-order"]').attributes("aria-disabled")).toBe("true");
  });

  it("still offers escalation once a work order exists, since the alert itself is untouched", async () => {
    getAlert.mockResolvedValue(makeDetail({ work_order: makeWorkOrder() }));

    const { wrapper } = await mountDetailPage();
    await wrapper.get('[data-test="disposition-reason"]').setValue("交上去");

    expect(wrapper.get('[data-test="escalate-alert"]').attributes("aria-disabled")).toBe("false");
    expect(wrapper.get('[data-test="derive-work-order"]').attributes("aria-disabled")).toBe("true");
  });

  it("hides the disposition form from a role that cannot act, and says why", async () => {
    currentEmployee.value = { real_name: "刘经理", employee_role: ACCOUNT_MANAGER };
    const { wrapper } = await mountDetailPage();

    expect(wrapper.find('[data-test="disposition"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="read-only-hint"]').text()).toContain("由风控专员完成");
    // 只读角色仍然看得到依据：看得见与能处置是两件事。
    expect(wrapper.get('[data-test="rule-hits-table"]').text()).toContain("交易金额");
  });

  it("hides the disposition form once the alert has been judged", async () => {
    getAlert.mockResolvedValue(makeDetail({ status: "已排除", handled_by_name: "周风控" }));
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR };

    const { wrapper } = await mountDetailPage();

    expect(wrapper.find('[data-test="disposition"]').exists()).toBe(false);
    expect(wrapper.find('[data-test="read-only-hint"]').exists()).toBe(false);
  });

  it("renders a forbidden state when the alert is outside the viewer's book", async () => {
    getAlert.mockRejectedValue(
      new ApiError({
        code: 403,
        message: "该预警不在你名下客户的范围内，无权查看",
        data: null,
        trace_id: "",
      }),
    );
    currentEmployee.value = { real_name: "刘经理", employee_role: ACCOUNT_MANAGER };

    const { wrapper } = await mountDetailPage();

    expect(wrapper.get('[data-test="alert-forbidden"]').text()).toContain("无权查看");
    expect(wrapper.get('[data-test="alert-forbidden"]').text()).toContain("名下客户");
    expect(wrapper.find('[data-test="rule-hits-table"]').exists()).toBe(false);
  });

  it("surfaces a submission failure instead of pretending the disposition went through", async () => {
    excludeAlert.mockRejectedValue(
      new ApiError({ code: 409, message: "该预警已处置，不能重复处置", data: null, trace_id: "" }),
    );
    const { wrapper } = await mountDetailPage();

    await wrapper.get('[data-test="disposition-reason"]').setValue("再排除一次");
    await wrapper.get('[data-test="exclude-alert"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-test="action-error"]').text()).toContain("已处置");
  });

  it("has an independent URL and can go back to the alert list", async () => {
    const { wrapper, router } = await mountDetailPage("42");

    expect(getAlert).toHaveBeenCalledWith(42);

    await wrapper.get('[data-test="back-to-alerts"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("risk-monitoring");
  });
});
