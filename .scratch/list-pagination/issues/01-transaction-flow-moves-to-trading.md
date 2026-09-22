# 01 — 交易流水归位到交易模块

**What to build:** 客户在「交易」页（而非「我的资产」页）看到自己的交易流水。这是一次**零行为变更**的搬移：流水仍全量展示、筛选仍可用，只是位置从资产页移到交易页，接口前缀从 `/api/customer/assets/transactions` 移到 `/api/customer/transactions`。

**Blocked by:** None — can start immediately（`customer_assets` 与 `customer_transactions` 均已实现）

**Status:** ready-for-agent

- [ ] 后端读接口 `GET /api/customer/assets/transactions` → `GET /api/customer/transactions`，返回形状**不变**（仍是 `{transactions: [...]}`，本 ticket 不分页）
- [ ] 流水读 service（`list_transactions` + `_serialize_flow`/`serialize_transaction`/`serialize_transfer`/`serialize_deposit` + `_transaction_rows`/`_transfer_rows`/`_deposit_rows` + 排序兜底常量）从 `customer_assets` 迁出，落到 `customer_transactions` 对应的读模块；`customer_assets` 保留 `get_assets`/`list_holding_shares` 等资产读，不动
- [ ] 前端 `TransactionHistory.vue` 从 `assets/` 迁到 `trading/`；`AssetsPage.vue` 移除流水卡片；`TradingPage.vue` 用 el-tabs 分「下单 / 交易流水」，流水渲染在第二个 tab
- [ ] `listTransactions` 从 `assets/api.ts` 迁到 `trading/api.ts`；`TransactionRecord`/`TransactionList`/`TransactionFilters` 从 `assets/types.ts` 迁到 `trading/types.ts`（`Holding`/`CustomerAssets`/`LookThrough` 等资产类型留在原处）
- [ ] 相关 spec 同步迁移（`TransactionHistory`、`AssetsPage`、`TradingPage`），行为断言不变——流水全量展示、日期/类型筛选可用
- [ ] 交易页下单四个表单（申购/赎回/转账/充值）行为不变；资产页不再出现流水卡片

**实现落点：** `backend/app/api/customer_transactions.py`（新增 GET）、流水读 service 落点、`apps/customer/src/trading/`（`TransactionHistory.vue`、`api.ts`、`types.ts`、`TradingPage.vue` 加 tab）、`apps/customer/src/assets/AssetsPage.vue`（移除引用）、两端 spec。

**验收：** 客户登录后进「交易」页 → 切换「交易流水」tab → 看到与原先资产页一致的流水（筛选可用）；资产页不再有流水。
