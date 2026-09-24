// 规则编辑器表单的派生逻辑：全部从 `GET /schema` 的载荷推出来。
//
// 单独测是因为这几件事都是「一处口径、两个使用者」：字段换了算子下拉要收敛、算子换了阈值
// 输入框要变形、时间窗算子才要窗长。它们的对错不该依赖一次 Element Plus 的挂载。
import { describe, expect, it } from "vitest";
import {
  operatorChoices,
  thresholdKeys,
  thresholdKeyLabel,
  thresholdPayload,
  usesWindowHours,
  valueRangeHint,
} from "./ruleEditor";
import type { RiskRuleSchema } from "./types";

const SCHEMA: RiskRuleSchema = {
  categories: ["大额交易", "频繁交易"],
  fields: [
    {
      key: "amount",
      label: "交易金额",
      description: "本笔交易的成交金额",
      allowed_operators: ["gte", "between", "window_count_gte"],
      value_range: { min: "0", max: null, min_inclusive: false, max_inclusive: true, text: "> 0" },
    },
    {
      key: "product_id",
      label: "产品标识",
      description: "交易对应的产品标识",
      allowed_operators: ["window_distinct_count_gte"],
      value_range: null,
    },
  ],
  operators: [
    { key: "gte", label: "大于等于", symbol: "≥", scope: "single", threshold_keys: ["value"] },
    { key: "between", label: "落在区间内", symbol: "∈", scope: "single", threshold_keys: ["min", "max"] },
    {
      key: "window_count_gte",
      label: "时间窗内计数",
      symbol: "≥",
      scope: "window",
      threshold_keys: ["value"],
    },
    {
      key: "daily_count_gte",
      label: "同日计数",
      symbol: "≥",
      scope: "daily",
      threshold_keys: ["value"],
    },
    {
      key: "window_distinct_count_gte",
      label: "时间窗内去重计数",
      symbol: "≥",
      scope: "window",
      threshold_keys: ["value"],
    },
  ],
};

describe("算子下拉的收敛", () => {
  it("按字段声明的允许清单过滤，顺序跟注册表", () => {
    expect(operatorChoices(SCHEMA, "amount").map((operator) => operator.key)).toEqual([
      "gte",
      "between",
      "window_count_gte",
    ]);
    // 标识类字段只配得上不去比数值的那一个算子。
    expect(operatorChoices(SCHEMA, "product_id").map((operator) => operator.key)).toEqual([
      "window_distinct_count_gte",
    ]);
  });

  it("还没选字段、或载荷没到时不给出任何算子", () => {
    expect(operatorChoices(SCHEMA, "")).toEqual([]);
    expect(operatorChoices(null, "amount")).toEqual([]);
  });
});

describe("阈值输入的形状", () => {
  it("键名由算子的 threshold_keys 决定", () => {
    expect(thresholdKeys(SCHEMA, "gte")).toEqual(["value"]);
    expect(thresholdKeys(SCHEMA, "between")).toEqual(["min", "max"]);
    expect(thresholdKeys(SCHEMA, "unknown")).toEqual([]);
  });

  it("只有时间窗算子要窗长", () => {
    expect(usesWindowHours(SCHEMA, "window_count_gte")).toBe(true);
    expect(usesWindowHours(SCHEMA, "window_distinct_count_gte")).toBe(true);
    // 单笔与自然日算子都不带窗长：前者没有窗口，后者的窗口由「同日」给定。
    expect(usesWindowHours(SCHEMA, "gte")).toBe(false);
    expect(usesWindowHours(SCHEMA, "daily_count_gte")).toBe(false);
  });

  it("阈值键有可展示的中文，没登记过的原样显示", () => {
    expect(thresholdKeyLabel("value")).toBe("阈值");
    expect(thresholdKeyLabel("min")).toBe("下限");
    expect(thresholdKeyLabel("max")).toBe("上限");
    expect(thresholdKeyLabel("window_hours")).toBe("window_hours");
  });

  it("待提交的阈值只留当前算子的键，并去掉空白", () => {
    // 草稿里留着上一个算子用过的 `min` / `max`：换回 `gte` 之后它们不该跟着提交。
    const draft = { value: " 50000 ", min: "1", max: "2" };
    expect(thresholdPayload(SCHEMA, "gte", draft)).toEqual({ value: "50000" });
    expect(thresholdPayload(SCHEMA, "between", draft)).toEqual({ min: "1", max: "2" });
    // 还没填的键给空串，由后端说「阈值形状未通过」。
    expect(thresholdPayload(SCHEMA, "between", {})).toEqual({ min: "", max: "" });
  });
});

describe("值域提示", () => {
  it("有值域的字段给一句可展示的提示，没有的给 null", () => {
    expect(valueRangeHint(SCHEMA, "amount")).toBe("> 0");
    // 产品标识的阈值是去重后的产品数，不是字段取值，所以没有值域可声明。
    expect(valueRangeHint(SCHEMA, "product_id")).toBeNull();
  });
});
