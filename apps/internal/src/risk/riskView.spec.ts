import { describe, expect, it } from "vitest";
import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER } from "../auth/identity";
import { canDeriveWorkOrder, canDispose, levelTagType, sortAlerts, statusTagType } from "./riskView";
import type { AlertSummary } from "./types";

function alert(id: number, confidence: number): AlertSummary {
  return {
    id,
    customer_id: 1,
    customer_name: "王客户",
    alert_type: "大额转账",
    alert_level: "重度",
    confidence,
    rule_codes: ["R001"],
    rule_count: 1,
    transaction_ids: [],
    status: "未处理",
    created_at: "2026-09-18T10:00:00",
    work_order_id: null,
    work_order_status: null,
  };
}

describe("预警的处置权限", () => {
  it("只有风控专员能处置未处理的预警", () => {
    expect(canDispose(RISK_OFFICER, "未处理")).toBe(true);
    expect(canDispose(RISK_OFFICER, "已排除")).toBe(false);
    expect(canDispose(ADVISOR, "未处理")).toBe(false);
    expect(canDispose(ACCOUNT_MANAGER, "未处理")).toBe(false);
  });

  it("已经派生过工单的预警不再给派生入口", () => {
    expect(canDeriveWorkOrder(RISK_OFFICER, { status: "未处理", work_order_id: null })).toBe(true);
    expect(canDeriveWorkOrder(RISK_OFFICER, { status: "未处理", work_order_id: 12 })).toBe(false);
    expect(canDeriveWorkOrder(ADVISOR, { status: "未处理", work_order_id: null })).toBe(false);
  });
});

describe("预警排序与标签", () => {
  it("默认保持服务端顺序（最新在前）", () => {
    const alerts = [alert(3, 0.2), alert(2, 0.9)];
    expect(sortAlerts(alerts, "created_desc").map((item) => item.id)).toEqual([3, 2]);
  });

  it("按置信度排序时并列的新的在前，且不改动原数组", () => {
    const alerts = [alert(3, 0.5), alert(1, 0.5), alert(2, 0.9)];
    const sorted = sortAlerts(alerts, "confidence_desc");

    expect(sorted.map((item) => item.id)).toEqual([2, 3, 1]);
    expect(alerts.map((item) => item.id)).toEqual([3, 1, 2]);
  });

  it("等级与状态映射到标签色", () => {
    expect(levelTagType("重度")).toBe("danger");
    expect(levelTagType("轻度")).toBe("info");
    expect(statusTagType("已排除")).toBe("info");
    expect(statusTagType("已升级")).toBe("success");
    expect(statusTagType("未处理")).toBe("warning");
  });
});
