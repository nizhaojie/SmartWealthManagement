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

export type CustomerAssets = {
  risk_level: RiskLevel | null;
  risk_level_valid_until: string | null;
  total_market_value: string;
  holding_count: number;
  holdings: Holding[];
};

export type TransactionRecord = {
  transaction_no: string;
  transaction_type: string;
  product_code: string;
  product_name: string;
  amount: string;
  shares: string;
  nav: string;
  fee: string;
  status: string;
  traded_at: string;
};

export type TransactionList = {
  transactions: TransactionRecord[];
};

export type TransactionFilters = {
  start_date?: string;
  end_date?: string;
  transaction_type?: string;
};
