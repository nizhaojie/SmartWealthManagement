import type { TransactionRecord } from "../assets/types";

/**
 * 一次交易受理的结果：成交那一笔的完整流水，加上成交之后的可用余额。
 *
 * 成交口径只有一处（`app.order_acceptance.service`，ADR-0018）：申购扣 `金额 + 手续费`、
 * 转账扣全额、赎回增加 `金额 - 手续费`、充值增加全额。这里拿到的 `available_balance` 是
 * 受理侧算好的结果，界面不再自己减。
 */
export type AcceptanceResult = {
  transaction: TransactionRecord;
  available_balance: string;
};

/** 申购：产品由客户指名（没有候选池兜底，越级由受理侧拒绝），金额是元。 */
export type PurchaseRequest = {
  product_code: string;
  amount: string;
};

/** 赎回：按份额赎回，金额由受理侧按当前净值算出。 */
export type RedemptionRequest = {
  product_code: string;
  shares: string;
};

/** 转账：收款人是机构之外的对手方，只有姓名与账号，没有产品（ADR-0019）。 */
export type TransferRequest = {
  payee_name: string;
  payee_account: string;
  amount: string;
};

/** 充值：钱从机构之外进入资金账户，只记金额、不记来源（Q2）。 */
export type DepositRequest = {
  amount: string;
};
