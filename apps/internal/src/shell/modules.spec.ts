// 模块清单与角色可见性：这是「谁看得见什么」的唯一事实源，值得钉住。
import { describe, expect, it } from "vitest";
import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER } from "../auth/identity";
import { MODULES, visibleModules } from "./modules";

const EXPECTED_ORDER = [
  "知识库管理",
  "数据分析",
  "客户画像",
  "投顾助手",
  "风控监测",
  "工单管理",
  "客户关系",
];

describe("角色可见模块", () => {
  it("七个模块按固定顺序排列", () => {
    expect(MODULES.map((module) => module.label)).toEqual(EXPECTED_ORDER);
  });

  it("理财顾问可见 6 项、客户经理 5 项、风控专员 4 项", () => {
    expect(visibleModules(ADVISOR)).toHaveLength(6);
    expect(visibleModules(ACCOUNT_MANAGER)).toHaveLength(5);
    expect(visibleModules(RISK_OFFICER)).toHaveLength(4);
  });

  it("工单管理已从风控监测拆成独立模块，且三个角色都可见", () => {
    const workOrders = MODULES.find((module) => module.id === "work-orders");
    expect(workOrders?.path).toBe("/work-orders");
    expect(workOrders?.roles).toHaveLength(3);
  });

  it("客户关系只对客户经理开放，且描述不再承诺「服务记录」", () => {
    const relations = MODULES.find((module) => module.id === "customer-relations");
    expect(relations?.roles).toEqual([ACCOUNT_MANAGER]);
    expect(relations?.description).not.toContain("服务记录");
  });

  it("没有角色时没有可见模块", () => {
    expect(visibleModules(null)).toEqual([]);
  });
});
