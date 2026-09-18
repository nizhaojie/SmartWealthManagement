import { describe, expect, it } from "vitest";
import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER } from "../auth/identity";
import { canCreateWorkOrder, canHandleWorkOrder, transitionFromLabel, workOrderTagType } from "./workOrderView";

describe("工单流转权限", () => {
  it("只有风控专员能接单与办结，且只在非终态", () => {
    expect(canHandleWorkOrder(RISK_OFFICER, "待处理")).toBe(true);
    expect(canHandleWorkOrder(RISK_OFFICER, "处理中")).toBe(true);
    expect(canHandleWorkOrder(RISK_OFFICER, "已完成")).toBe(false);
    expect(canHandleWorkOrder(RISK_OFFICER, "已关闭")).toBe(false);
    expect(canHandleWorkOrder(ADVISOR, "待处理")).toBe(false);
    expect(canHandleWorkOrder(ACCOUNT_MANAGER, "处理中")).toBe(false);
  });

  it("外部建单同样只放开给风控专员", () => {
    expect(canCreateWorkOrder(RISK_OFFICER)).toBe(true);
    expect(canCreateWorkOrder(ADVISOR)).toBe(false);
  });

  it("建单那一跳没有来源状态，显示为「建单」", () => {
    expect(transitionFromLabel(null)).toBe("建单");
    expect(transitionFromLabel("待处理")).toBe("待处理");
  });

  it("状态映射到标签色", () => {
    expect(workOrderTagType("待处理")).toBe("warning");
    expect(workOrderTagType("处理中")).toBe("primary");
    expect(workOrderTagType("已完成")).toBe("success");
    expect(workOrderTagType("已关闭")).toBe("info");
  });
});
