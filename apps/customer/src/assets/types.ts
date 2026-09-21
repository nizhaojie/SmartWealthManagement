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

/**
 * 合并流水里的**一种形状**：申购、赎回与转账共用它（服务端的 `_serialize_flow`）。
 *
 * 产品的三项与收款人的两项各自只对一类记录成立，另一类一律为空——转账没有产品，
 * 申赎没有收款人。写死成非空会让界面把「不存在」读成「有值」。
 */
export type TransactionRecord = {
  transaction_no: string;
  transaction_type: string;
  product_code: string | null;
  product_name: string | null;
  amount: string;
  shares: string | null;
  nav: string | null;
  fee: string | null;
  status: string;
  traded_at: string;
  payee_name: string | null;
  payee_account: string | null;
};

export type TransactionList = {
  transactions: TransactionRecord[];
};

export type TransactionFilters = {
  start_date?: string | null;
  end_date?: string | null;
  transaction_type?: string;
};
