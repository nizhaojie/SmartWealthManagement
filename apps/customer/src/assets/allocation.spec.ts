import { describe, expect, it } from "vitest";
import {
  ASSET_CLASS_ORDER,
  PRODUCT_RISK_LEVEL_ORDER,
  assetClassOf,
  buildActualAllocation,
  buildRiskLevelDistribution,
} from "./allocation";
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

describe("实际配置", () => {
  it("把同一资产大类下的持仓市值加在一起", () => {
    const holdings = [
      makeHolding({ market_value: "20000.00" }),
      makeHolding({ product_code: "F000002", product_type: "结构性存款", market_value: "8000.00" }),
      makeHolding({ product_code: "F000004", product_type: "股票基金", market_value: "5000.00" }),
    ];

    expect(buildActualAllocation(holdings)).toEqual([
      { name: "现金", value: 28000 },
      { name: "股票", value: 5000 },
    ]);
  });

  it("类别按资产大类的固定顺序排列，不按市值大小重排", () => {
    const holdings = [
      makeHolding({ product_type: "股票基金", market_value: "500.00" }),
      makeHolding({ product_code: "F000002", product_type: "债券基金", market_value: "90000.00" }),
      makeHolding({ product_code: "F000003", product_type: "货币基金", market_value: "1000.00" }),
    ];

    expect(buildActualAllocation(holdings).map((slice) => slice.name)).toEqual(["现金", "债券", "股票"]);
  });

  it("由持仓聚合得出，与画像里的目标配置无关", () => {
    expect(buildActualAllocation([])).toEqual([]);
  });

  it("认不出的产品类型归入另类，不从图上消失", () => {
    expect(assetClassOf("货币基金")).toBe("现金");
    expect(assetClassOf("某新产品")).toBe("另类");
    expect(buildActualAllocation([makeHolding({ product_type: "某新产品" })])).toEqual([
      { name: "另类", value: 20420 },
    ]);
  });
});

describe("持仓按产品风险等级的分布", () => {
  it("类别固定按 R1 到 R5 排列，不按市值大小重排", () => {
    const holdings = [
      makeHolding({ product_risk_level: "R4", market_value: "80000.00" }),
      makeHolding({ product_code: "F000002", product_risk_level: "R2", market_value: "2000.00" }),
      makeHolding({ product_code: "F000003", product_risk_level: "R5", market_value: "30000.00" }),
    ];

    expect(buildRiskLevelDistribution(holdings).map((slice) => slice.name)).toEqual([
      ...PRODUCT_RISK_LEVEL_ORDER,
    ]);
    expect(buildRiskLevelDistribution(holdings).map((slice) => slice.value)).toEqual([
      0, 2000, 0, 80000, 30000,
    ]);
  });

  it("没有持仓的等级也占一个位置，不会因为数值为零而缺席", () => {
    const slices = buildRiskLevelDistribution([makeHolding({ product_risk_level: "R3" })]);

    expect(slices).toHaveLength(5);
    expect(slices[2]).toEqual({ name: "R3", value: 20420 });
  });

  it("空持仓得到一组全零的类别，交由图表判断为无数据可画", () => {
    expect(buildRiskLevelDistribution([])).toEqual(
      PRODUCT_RISK_LEVEL_ORDER.map((level) => ({ name: level, value: 0 })),
    );
  });

  it("资产大类的固定顺序是五个类别", () => {
    expect(ASSET_CLASS_ORDER).toHaveLength(5);
  });
});
