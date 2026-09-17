import { describe, expect, it } from "vitest";
import { ApiError } from "@wealth/shared";
import { ADVISOR, ACCOUNT_MANAGER, RISK_OFFICER } from "../auth/identity";
import {
  canDeriveWorkOrder,
  canDispose,
  canHandleWorkOrder,
  confidenceText,
  errorMessage,
  levelTagType,
  sortAlerts,
  statusTagType,
  workOrderTagType,
} from "./riskView";
import type { AlertSummary } from "./types";

function makeAlert(overrides: Partial<AlertSummary> = {}): AlertSummary {
  return {
    id: 1,
    customer_id: 1,
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

describe("sortAlerts", () => {
  it("keeps the server order when sorting by creation time, since the server already did it", () => {
    const alerts = [makeAlert({ id: 3 }), makeAlert({ id: 2 }), makeAlert({ id: 1 })];

    expect(sortAlerts(alerts, "created_desc").map((alert) => alert.id)).toEqual([3, 2, 1]);
  });

  it("sorts by confidence in both directions", () => {
    const alerts = [
      makeAlert({ id: 1, confidence: 0.2 }),
      makeAlert({ id: 2, confidence: 0.9 }),
      makeAlert({ id: 3, confidence: 0.5 }),
    ];

    expect(sortAlerts(alerts, "confidence_desc").map((alert) => alert.id)).toEqual([2, 3, 1]);
    expect(sortAlerts(alerts, "confidence_asc").map((alert) => alert.id)).toEqual([1, 3, 2]);
  });

  it("breaks ties with the newer alert first so the order never drifts", () => {
    const alerts = [
      makeAlert({ id: 4, confidence: 0.5 }),
      makeAlert({ id: 9, confidence: 0.5 }),
      makeAlert({ id: 6, confidence: 0.5 }),
    ];

    expect(sortAlerts(alerts, "confidence_desc").map((alert) => alert.id)).toEqual([9, 6, 4]);
    expect(sortAlerts(alerts, "confidence_asc").map((alert) => alert.id)).toEqual([9, 6, 4]);
  });

  it("does not mutate the list it was handed", () => {
    const alerts = [makeAlert({ id: 1, confidence: 0.2 }), makeAlert({ id: 2, confidence: 0.9 })];

    sortAlerts(alerts, "confidence_desc");

    expect(alerts.map((alert) => alert.id)).toEqual([1, 2]);
  });
});

describe("canDispose", () => {
  it("lets only risk officers judge an alert, and only while it is untouched", () => {
    expect(canDispose(RISK_OFFICER, "未处理")).toBe(true);
    expect(canDispose(RISK_OFFICER, "已排除")).toBe(false);
    expect(canDispose(ADVISOR, "未处理")).toBe(false);
    expect(canDispose(ACCOUNT_MANAGER, "未处理")).toBe(false);
    expect(canDispose(undefined, "未处理")).toBe(false);
  });
});

describe("canDeriveWorkOrder", () => {
  it("offers the entry point only while no work order has been derived yet", () => {
    expect(canDeriveWorkOrder(RISK_OFFICER, { status: "未处理", work_order_id: null })).toBe(true);
    expect(canDeriveWorkOrder(RISK_OFFICER, { status: "未处理", work_order_id: 7 })).toBe(false);
    expect(canDeriveWorkOrder(RISK_OFFICER, { status: "已升级", work_order_id: null })).toBe(false);
    expect(canDeriveWorkOrder(ADVISOR, { status: "未处理", work_order_id: null })).toBe(false);
  });
});

describe("canHandleWorkOrder", () => {
  it("only lets a risk officer push a work order that is not finished yet", () => {
    expect(canHandleWorkOrder(RISK_OFFICER, "待处理")).toBe(true);
    expect(canHandleWorkOrder(RISK_OFFICER, "处理中")).toBe(true);
    expect(canHandleWorkOrder(RISK_OFFICER, "已完成")).toBe(false);
    expect(canHandleWorkOrder(RISK_OFFICER, "已关闭")).toBe(false);
    expect(canHandleWorkOrder(ADVISOR, "待处理")).toBe(false);
    expect(canHandleWorkOrder(undefined, "待处理")).toBe(false);
  });
});

describe("presentation helpers", () => {
  it("maps levels and statuses onto tag types that keep severity legible", () => {
    expect(levelTagType("重度")).toBe("danger");
    expect(levelTagType("中度")).toBe("warning");
    expect(levelTagType("轻度")).toBe("info");

    expect(statusTagType("未处理")).toBe("warning");
    expect(statusTagType("已排除")).toBe("info");
    expect(statusTagType("已升级")).toBe("success");

    expect(workOrderTagType("待处理")).toBe("warning");
    expect(workOrderTagType("处理中")).toBe("primary");
    expect(workOrderTagType("已完成")).toBe("success");
    expect(workOrderTagType("已关闭")).toBe("info");
  });

  it("shows confidence with two decimals, matching how it is computed", () => {
    expect(confidenceText(0.1)).toBe("0.10");
    expect(confidenceText(0.85)).toBe("0.85");
    expect(confidenceText(1)).toBe("1.00");
  });

  it("passes the backend's own message through, and only falls back when there is none", () => {
    const forbidden = new ApiError({
      code: 403,
      message: "该预警不在你名下客户的范围内，无权查看",
      data: null,
      trace_id: "",
    });

    expect(errorMessage(forbidden, "加载失败")).toBe("该预警不在你名下客户的范围内，无权查看");
    expect(errorMessage(new Error("网络不可用"), "加载失败")).toBe("网络不可用");
    expect(errorMessage(null, "加载失败")).toBe("加载失败");
  });
});
