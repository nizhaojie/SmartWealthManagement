import { describe, expect, it } from "vitest";
import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER } from "../auth/identity";
import {
  ALERT_SORT_OPTIONS,
  alertSourceNote,
  alertSourceTagType,
  canDeriveWorkOrder,
  canDispose,
  levelTagType,
  statusTagType,
} from "./riskView";

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

describe("预警排序选项", () => {
  it("排序都在服务端做：选项里给出「按等级（重到轻）」，且默认最新在前", () => {
    // 这里不排序，只交代下拉里有哪些档、默认是哪一档——排序结果由后端给出
    // （ADR-0024），前端不再留一份本地排序。
    expect(ALERT_SORT_OPTIONS[0].value).toBe("created_desc");
    expect(ALERT_SORT_OPTIONS.map((option) => option.value)).toContain("level_desc");
    expect(ALERT_SORT_OPTIONS.every((option) => option.label.length > 0)).toBe(true);
  });
});

describe("预警标签", () => {
  it("等级与状态映射到标签色", () => {
    expect(levelTagType("重度")).toBe("danger");
    expect(levelTagType("轻度")).toBe("info");
    expect(statusTagType("已排除")).toBe("info");
    expect(statusTagType("已升级")).toBe("success");
    expect(statusTagType("未处理")).toBe("warning");
  });
});

describe("预警来源的标注", () => {
  it("内部补录用警示色，客户发起用中性色", () => {
    expect(alertSourceTagType("内部补录")).toBe("warning");
    expect(alertSourceTagType("客户发起")).toBe("info");
  });

  it("只有内部补录需要补充说明：它没过业务校验", () => {
    expect(alertSourceNote("内部补录")).toContain("未经适当性与余额校验");
    expect(alertSourceNote("客户发起")).toBeNull();
  });
});
