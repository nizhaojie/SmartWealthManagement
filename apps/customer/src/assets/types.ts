import type { RiskLevel } from "../risk-assessment/types";

export type Holding = {
  product_code: string;
  product_name: string;
  product_type: string;
  product_risk_level: string;
  shares: string;
  cost_amount: string;
  market_value: string;
  profit_loss: string;
  profit_ratio: string;
};

/** 穿透树上的一个节点：kind 为 product 时可继续展开，asset 是展开的尽头。 */
export type LookThroughNode = {
  kind: "product" | "asset";
  code: string;
  name: string;
  depth: number;
  /** 占这笔持仓市值的比例，与 market_value 在各层级上保持一致。 */
  share: string;
  market_value: string;
  asset_category: string | null;
  children: LookThroughNode[];
};

/** 同一底层资产的多条路径合并后的结果。 */
export type UnderlyingAssetTotal = {
  asset_code: string;
  asset_name: string;
  asset_category: string;
  market_value: string;
  share: string;
  path_count: number;
};

export type LookThrough = {
  product_code: string;
  product_name: string;
  market_value: string;
  root: LookThroughNode;
  underlying_assets: UnderlyingAssetTotal[];
};

export type CustomerAssets = {
  risk_level: RiskLevel | null;
  risk_level_valid_until: string | null;
  total_market_value: string;
  holding_count: number;
  holdings: Holding[];
};
