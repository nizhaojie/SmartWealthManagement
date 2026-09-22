import { describe, expect, it } from "vitest";
import {
  TARGET_ALLOCATION_TOTAL,
  targetAllocationError,
  targetAllocationTotal,
} from "./onboarding";

describe("开户表单的目标配置", () => {
  it("合计按类别求和，缺席的类别记 0", () => {
    expect(targetAllocationTotal({ 股票: 60, 债券: 30, 现金: 10 })).toBe(100);
    expect(targetAllocationTotal({})).toBe(0);
  });

  it("浮点数不因为二进制误差被判成不合法", () => {
    expect(targetAllocationTotal({ 股票: 33.33, 债券: 33.33, 现金: 33.34 })).toBe(
      TARGET_ALLOCATION_TOTAL,
    );
    expect(targetAllocationError({ 股票: 33.33, 债券: 33.33, 现金: 33.34 })).toBeNull();
  });

  it("五项全为 0 是「没有填」，不是错误", () => {
    expect(targetAllocationError({ 股票: 0, 债券: 0, 现金: 0, 混合: 0, 另类: 0 })).toBeNull();
  });

  it("合计不是 100 时给出当前合计", () => {
    expect(targetAllocationError({ 股票: 80, 债券: 60, 现金: 40 })).toBe(
      "目标配置的各类占比合计必须为 100%（当前 180%）",
    );
    expect(targetAllocationError({ 股票: 30, 债券: 20 })).toBe(
      "目标配置的各类占比合计必须为 100%（当前 50%）",
    );
  });
});
