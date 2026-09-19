# 03 — 转账与客户侧流水合并读

**What to build:** 客户可以把余额转给机构之外的收款人。转账没有产品，因此落在自己的表里（ADR-0019）；但它与申购赎回一样是一笔交易事件。客户侧的「交易流水」改成两表合并读，否则转账行会整行消失在客户眼前。

**Blocked by:** 02 — 客户侧的申购与赎回

**Status:** implemented

- [x] 转账表与迁移：客户、金额、收款人姓名、收款人账号、成交时间；**没有产品**
- [x] 受理校验：余额充足、金额为正、收款人姓名与账号非空
- [x] 转账照常调用 `submit_transaction_event`——风控侧的 `TransactionEvent.product_id` 本就可空，无需改动
- [x] **放宽风控入口对产品的强校验**：现有实现无条件要求产品存在（`app/risk_monitoring/alerting.py` 的 `_require_product`），转账一接进来就会报「产品不存在」
- [x] 客户侧交易流水改成**两表合并读**：`app/customer_assets/service.py` 的 `INNER JOIN fin_product` 是漏点——**漏了不会报错，只是转账记录整行消失**
- [x] 合并后的流水按成交时间倒序；转账行的序列化没有产品名，而有收款人
- [x] 断言：转账不出现在 `fin_transaction`，但出现在客户侧流水里且带收款人信息
- [x] 断言：流水同时含申购、赎回、转账三类

**实现落点：** `backend/app/order_acceptance/service.py`（`transfer`）、迁移 `0025_transfer`、
`backend/tests/test_customer_transfer_and_merged_history.py`；表与模型 `fin_transfer` / `Transfer`
（`backend/app/db/models.py`）；客户侧接口在 `backend/app/api/customer_transactions.py`
（`POST /api/customer/transactions/transfer`）。

### 两处偏离 checklist 字面的地方（都是被 SQL 逼出来的，记在这里）

**转账表多了一列 `transfer_no`。** 合并读的两类记录共用一个形状，转账行需要一个流水号
（客户核对账目时每一行都要有编号可对），广播载荷里的 `transaction_no` 也要它。由 id
现编一个号不如按 `fin_transaction.transaction_no` 的同一形状（`TR` + 时间 + 随机后缀）
真的写一列。

**无产品的事件仍然要「先事务性落库」，只是那一行在 `fin_transfer` 里。** 入海口
（`alerting.submit_transaction_event`）对两类事件走同一个三步顺序：受理侧把转账行与
余额的变动写在同一个会话里并 `flush`，入海口提交它、再广播、最后过规则引擎。它因此
返回 `Transaction | None`——转账没有 `fin_transaction` 行可返回。

顺带定下两个后果：

- 转账的预警**不填** `RiskAlert.transaction_ids`。那一列存的是 `fin_transaction` 的
  标识，两张表的 id 各自从 1 开始，混着填会让预警详情按 id 回查到另一笔毫不相干的
  交易——那是「看起来完全正常」的那种错。转账的金额与类型仍在命中依据里。
- **历史回溯也要读两张表**（`alerting._history_events`）。只读 `fin_transaction` 不会
  报错，只会让窗口与累计类规则少算几笔转账，是静默漏报。
- 交接给 #04：预警的来源标注（客户发起 / 内部补录）依据是**有无经办员工**，而
  `fin_transfer` 上根本没有经办员工这一列，转账预警查不出这个依据。做 #04 时要么
  把「无 `transaction_ids`」当作客户发起的判据并写下来，要么明确转账预警不标来源。

### 前端不在本 issue 内

流水列表渲染三类记录（转账行显示收款人）是 #08 的事；本 issue 只保证接口把转账行连
收款人信息一起给出。
