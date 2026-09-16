import { describe, expect, it } from "vitest";
import { ALLOCATION_CATEGORY_ORDER, actualAllocationSeries, targetAllocationSeries } from "./allocation";
import type { Holding } from "./types";

function makeHolding(overrides: Partial<Holding> = {}): Holding {
  return {
    product_code: "F000001",
    product_name: "天枢货币基金",
    product_type: "货币基金",
    product_risk_level: "R1",
    shares: "20000.0000",
    cost_amount: "20000.00",
    market_value: "20420.00",
    profit_loss: "420.00",
    profit_ratio: "2.1000",
    ...overrides,
  };
}

describe("目标配置", () => {
  it("按固定类别顺序展开，画像里没有的类别（混合）补零", () => {
    const series = targetAllocationSeries({ 股票: 40, 债券: 35, 现金: 15, 另类: 10 });
    expect(series).toEqual([
      { name: "现金", value: 15 },
      { name: "债券", value: 35 },
      { name: "混合", value: 0 },
      { name: "股票", value: 40 },
      { name: "另类", value: 10 },
    ]);
  });

  it("空画像得到一组全零的类别，而不是空数组", () => {
    expect(targetAllocationSeries({})).toEqual(
      ALLOCATION_CATEGORY_ORDER.map((name) => ({ name, value: 0 })),
    );
  });
});

describe("实际配置", () => {
  it("按固定类别顺序展开，不丢弃数值为零的类别", () => {
    const holdings = [makeHolding({ product_type: "货币基金", market_value: "20000.00" })];
    expect(actualAllocationSeries(holdings).map((slice) => slice.name)).toEqual([
      ...ALLOCATION_CATEGORY_ORDER,
    ]);
    expect(actualAllocationSeries(holdings)).toEqual([
      { name: "现金", value: 20000 },
      { name: "债券", value: 0 },
      { name: "混合", value: 0 },
      { name: "股票", value: 0 },
      { name: "另类", value: 0 },
    ]);
  });

  it("同一资产大类下的持仓市值加在一起", () => {
    const holdings = [
      makeHolding({ market_value: "20000.00" }),
      makeHolding({ product_code: "F000002", product_type: "结构性存款", market_value: "8000.00" }),
      makeHolding({ product_code: "F000004", product_type: "股票基金", market_value: "5000.00" }),
    ];

    const series = actualAllocationSeries(holdings);
    expect(series.find((slice) => slice.name === "现金")?.value).toBe(28000);
    expect(series.find((slice) => slice.name === "股票")?.value).toBe(5000);
  });

  it("空持仓得到一组全零的类别，交由图表判断为无数据可画", () => {
    expect(actualAllocationSeries([])).toEqual(
      ALLOCATION_CATEGORY_ORDER.map((name) => ({ name, value: 0 })),
    );
  });

  it("认不出的产品类型归入另类，不从图上消失", () => {
    expect(actualAllocationSeries([makeHolding({ product_type: "某新产品" })])).toEqual([
      { name: "现金", value: 0 },
      { name: "债券", value: 0 },
      { name: "混合", value: 0 },
      { name: "股票", value: 0 },
      { name: "另类", value: 20420 },
    ]);
  });
});
