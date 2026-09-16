import type { CategoryValue } from "@wealth/shared";
import type { Holding } from "./types";

// 两组类别顺序必须一致，对比才读得出来（ADR-0006）——因此这里的顺序固定，
// 且两组都按这个顺序补零，不因某一组没有这个类别就把它从轴上去掉。
export const ALLOCATION_CATEGORY_ORDER = ["现金", "债券", "混合", "股票", "另类"] as const;

export type AssetClass = (typeof ALLOCATION_CATEGORY_ORDER)[number];

// 与 apps/customer/src/assets/allocation.ts 同一份映射关系，但两个应用各自
// 打包（ADR-0003），这张小表按值复制一份而不是跨应用互相 import。
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

function assetClassOf(productType: string): AssetClass {
  return ASSET_CLASS_BY_PRODUCT_TYPE[productType] ?? "另类";
}

function marketValueOf(holding: Holding): number {
  const value = Number(holding.market_value);
  return Number.isFinite(value) ? value : 0;
}

function roundToCents(value: number): number {
  return Math.round(value * 100) / 100;
}

/** 目标配置：来自画像，按固定类别顺序补零——画像里没有「混合」这个目标类别。 */
export function targetAllocationSeries(target: Record<string, number>): CategoryValue[] {
  return ALLOCATION_CATEGORY_ORDER.map((assetClass) => ({
    name: assetClass,
    value: target[assetClass] ?? 0,
  }));
}

/**
 * 实际配置：由持仓市值按资产大类聚合，按同一固定顺序补零。
 * 与客户端「我的资产」页的 buildActualAllocation 不同的是这里不丢零值类别——
 * 对比图的两组必须站在同一根类别轴上，缺席的类别会让两组错位。
 */
export function actualAllocationSeries(holdings: readonly Holding[]): CategoryValue[] {
  const totals = new Map<AssetClass, number>();
  for (const holding of holdings) {
    const assetClass = assetClassOf(holding.product_type);
    totals.set(assetClass, (totals.get(assetClass) ?? 0) + marketValueOf(holding));
  }

  return ALLOCATION_CATEGORY_ORDER.map((assetClass) => ({
    name: assetClass,
    value: roundToCents(totals.get(assetClass) ?? 0),
  }));
}
