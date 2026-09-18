import type { CategoryValue } from "@wealth/shared";
import { PRODUCT_RISK_LEVELS, type ProductRiskLevel } from "../products/types";
import type { Holding } from "./types";

// 资产大类说的是钱压在哪一类资产上；产品类型说的是能申购的东西是什么
// （货币基金、银行理财……）。两张图要回答的是前者，所以这里做一次归集。
export const ASSET_CLASS_ORDER = ["现金", "债券", "混合", "股票", "另类"] as const;

export type AssetClass = (typeof ASSET_CLASS_ORDER)[number];

// 资产大类由产品类型推导：这一层映射是近似，类别取目标配置所用的那几个
// （股票 / 债券 / 现金 / 另类）加上混合。
const ASSET_CLASS_BY_PRODUCT_TYPE: Record<string, AssetClass> = {
  货币基金: "现金",
  结构性存款: "现金",
  债券基金: "债券",
  银行理财: "债券",
  混合基金: "混合",
  股票基金: "股票",
  信托产品: "另类",
  保险产品: "另类",
};

export function assetClassOf(productType: string): AssetClass {
  return ASSET_CLASS_BY_PRODUCT_TYPE[productType] ?? "另类";
}

function marketValueOf(holding: Holding): number {
  const value = Number(holding.market_value);
  return Number.isFinite(value) ? value : 0;
}

function roundToCents(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * 实际配置：由当前持仓的市值按资产大类聚合得出。
 * 它表达事实，因此不读客户画像里的目标配置（ADR-0006）——那是意愿，是另一回事。
 */
export function buildActualAllocation(holdings: readonly Holding[]): CategoryValue[] {
  const totals = new Map<AssetClass, number>();
  for (const holding of holdings) {
    const assetClass = assetClassOf(holding.product_type);
    totals.set(assetClass, (totals.get(assetClass) ?? 0) + marketValueOf(holding));
  }

  const known = ASSET_CLASS_ORDER.filter((assetClass) => totals.has(assetClass));
  return known.map((assetClass) => ({
    name: assetClass,
    value: roundToCents(totals.get(assetClass) ?? 0),
  }));
}

/**
 * 持仓按产品风险等级的市值分布。
 * 类别固定按 R1 到 R5 排列，没有持仓的等级也占一个位置——顺序本身携带信息
 * （风险由低到高），按数值重排就把它丢掉了。
 */
export function buildRiskLevelDistribution(holdings: readonly Holding[]): CategoryValue[] {
  const totals = new Map<ProductRiskLevel, number>();
  for (const holding of holdings) {
    const level = holding.product_risk_level as ProductRiskLevel;
    // 库里 product_risk_level 有 R1 到 R5 的约束，这里的判断是把类型收窄到五个等级。
    if (!PRODUCT_RISK_LEVELS.includes(level)) continue;
    totals.set(level, (totals.get(level) ?? 0) + marketValueOf(holding));
  }

  return PRODUCT_RISK_LEVELS.map((level) => ({
    name: level,
    value: roundToCents(totals.get(level) ?? 0),
  }));
}
