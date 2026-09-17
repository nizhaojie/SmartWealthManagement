import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@wealth/shared";
import { ADVISOR, RISK_OFFICER } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import type { WorkOrderDetail } from "./types";

const { getWorkOrder, acceptWorkOrder, completeWorkOrder, closeWorkOrder } = vi.hoisted(() => ({
  getWorkOrder: vi.fn(),
  acceptWorkOrder: vi.fn(),
  completeWorkOrder: vi.fn(),
  closeWorkOrder: vi.fn(),
}));

vi.mock("./api", () => ({ getWorkOrder, acceptWorkOrder, completeWorkOrder, closeWorkOrder }));

import WorkOrderDetailPage from "./WorkOrderDetailPage.vue";

function makeDetail(overrides: Partial<WorkOrderDetail> = {}): WorkOrderDetail {
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
    transitions: [
      {
        from_status: null,
        to_status: "待处理",
        handler_id: 4,
        handler_name: "周风控",
        reason: "金额与实际收入不匹配",
        handled_at: "2026-09-17T09:30:00",
      },
    ],
    ...overrides,
  };
}

async function mountDetailPage(workOrderId = "7") {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/risk-monitoring", name: "risk-monitoring", component: { template: "<div />" } },
      {
        path: "/risk-monitoring/work-orders/:workOrderId",
        name: "risk-work-order-detail",
        component: { template: "<div />" },
      },
    ],
  });
  await router.push(`/risk-monitoring/work-orders/${workOrderId}`);
  await router.isReady();
  const wrapper = mount(WorkOrderDetailPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return { wrapper, router };
}

describe("WorkOrderDetailPage", () => {
  beforeEach(() => {
    getWorkOrder.mockReset().mockResolvedValue(makeDetail());
    acceptWorkOrder.mockReset().mockResolvedValue(makeDetail({ status: "处理中" }));
    completeWorkOrder.mockReset().mockResolvedValue(makeDetail({ status: "已完成" }));
    closeWorkOrder.mockReset().mockResolvedValue(makeDetail({ status: "已关闭" }));
    currentEmployee.value = { real_name: "周风控", employee_role: RISK_OFFICER };
  });

  afterEach(() => {
    currentEmployee.value = null;
  });

  it("shows the work order's state and how it got there", async () => {
    const { wrapper } = await mountDetailPage();

    expect(wrapper.get('[data-test="work-order-status"]').text()).toContain("待处理");
    const transitions = wrapper.get('[data-test="transitions-table"]').text();
    expect(transitions).toContain("建单 → 待处理");
    expect(transitions).toContain("金额与实际收入不匹配");
    expect(transitions).toContain("周风控");
  });

  it("refuses to accept while the reason is empty", async () => {
    const { wrapper } = await mountDetailPage();

    expect(wrapper.get('[data-test="accept"]').attributes("aria-disabled")).toBe("true");
    await wrapper.get('[data-test="accept"]').trigger("click");
    await flushPromises();
    expect(acceptWorkOrder).not.toHaveBeenCalled();

    await wrapper.get('[data-test="transition-reason"]').setValue("我来核实资金来源");
    await flushPromises();
    expect(wrapper.get('[data-test="accept"]').attributes("aria-disabled")).toBe("false");

    await wrapper.get('[data-test="accept"]').trigger("click");
    await flushPromises();

    expect(acceptWorkOrder).toHaveBeenCalledWith(7, "我来核实资金来源");
  });

  it("requires a conclusion as well as a reason to complete, but only a reason to close", async () => {
    getWorkOrder.mockResolvedValue(makeDetail({ status: "处理中" }));
    const { wrapper } = await mountDetailPage();

    await wrapper.get('[data-test="transition-reason"]').setValue("核实完毕");
    await flushPromises();

    expect(wrapper.get('[data-test="complete"]').attributes("aria-disabled")).toBe("true");
    expect(wrapper.get('[data-test="close"]').attributes("aria-disabled")).toBe("false");

    await wrapper.get('[data-test="transition-conclusion"]').setValue("资金来源于工资卡，属正常交易");
    await flushPromises();
    expect(wrapper.get('[data-test="complete"]').attributes("aria-disabled")).toBe("false");

    await wrapper.get('[data-test="complete"]').trigger("click");
    await flushPromises();

    expect(completeWorkOrder).toHaveBeenCalledWith(7, {
      reason: "核实完毕",
      conclusion: "资金来源于工资卡，属正常交易",
    });
  });

  it("reflects the new status in the page after a transition", async () => {
    getWorkOrder.mockResolvedValue(makeDetail({ status: "处理中" }));
    const { wrapper } = await mountDetailPage();

    await wrapper.get('[data-test="transition-reason"]').setValue("客户已销户");
    await wrapper.get('[data-test="close"]').trigger("click");
    await flushPromises();

    expect(closeWorkOrder).toHaveBeenCalledWith(7, { reason: "客户已销户", conclusion: "" });
    expect(getWorkOrder).toHaveBeenCalledTimes(2);
  });

  it("offers no further transition once the work order is finished", async () => {
    getWorkOrder.mockResolvedValue(makeDetail({ status: "已完成" }));

    const { wrapper } = await mountDetailPage();

    expect(wrapper.find('[data-test="work-order-actions"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="terminal-hint"]').text()).toContain("不能再流转");
  });

  it("keeps a read-only role out of the transition form", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR };

    const { wrapper } = await mountDetailPage();

    expect(wrapper.find('[data-test="work-order-actions"]').exists()).toBe(false);
    expect(wrapper.get('[data-test="read-only-hint"]').text()).toContain("由风控专员完成");
  });

  it("surfaces a rejected transition instead of assuming it worked", async () => {
    getWorkOrder.mockResolvedValue(makeDetail({ status: "处理中" }));
    closeWorkOrder.mockRejectedValue(
      new ApiError({ code: 409, message: "工单当前状态不允许该流转", data: null, trace_id: "" }),
    );
    const { wrapper } = await mountDetailPage();

    await wrapper.get('[data-test="transition-reason"]').setValue("不做了");
    await wrapper.get('[data-test="close"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-test="action-error"]').text()).toContain("不允许该流转");
  });

  it("renders a forbidden state when the work order is outside the viewer's book", async () => {
    getWorkOrder.mockRejectedValue(
      new ApiError({
        code: 403,
        message: "该工单不在你名下客户的范围内，无权查看",
        data: null,
        trace_id: "",
      }),
    );

    const { wrapper } = await mountDetailPage();

    expect(wrapper.get('[data-test="work-order-forbidden"]').text()).toContain("无权查看");
    expect(wrapper.find('[data-test="transitions-table"]').exists()).toBe(false);
  });

  it("has an independent URL and can go back to the work order list", async () => {
    const { wrapper, router } = await mountDetailPage("21");

    expect(getWorkOrder).toHaveBeenCalledWith(21);

    await wrapper.get('[data-test="back-to-work-orders"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("risk-monitoring");
  });
});
