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
