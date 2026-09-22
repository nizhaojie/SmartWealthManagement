# 01 — 充值的载体与受理

**What to build:** 客户可以把机构外的钱充进自己的资金账户。充值的事实落在自己的表里（`fin_deposit`，ADR-0023 的延续 ADR-0019），并照常成为一笔交易事件——风控因此**第一次看得见入金**。做完这一份就有可演示的完整状态。

**Blocked by:** 无前置（`operation-advice-and-customer-trading` 的资金账户、受理服务与交易事件入海口，以及 `onboarding-funding-account-and-target-allocation` 的开户建账户，都已实现）

**Status:** ready-for-agent

- [ ] `fin_deposit` 表与迁移 `0029_deposit`：`deposit_no`、`customer_id`、`amount`、`create_time`；`CHECK amount > 0`；索引 `ix_fin_deposit_customer_id`；**没有 status 列**（受理通过即入账，Q5）
- [ ] 模型 `Deposit`（`backend/app/db/models.py`），形状与约束同 `Transfer`
- [ ] 受理服务 `order_acceptance.service.deposit()`：校验只有**金额 > 0** 与**资金账户存在**两条；`available_balance += _money(amount)`；落库与余额变动在同一个会话里，全部校验在落库之前（ADR-0018）
- [ ] **不设限额、不要风评**（Q7）：大额入金交给规则引擎，不在受理侧拒收
- [ ] 流水号前缀 `DP`，与 `TR` 同一形状（时间 + 随机后缀）——两类记录会并排出现在客户的同一个列表里
- [ ] 调用 `submit_transaction_event` 的**无产品分支**（`alerting._submit_recorded_fact`），传 `transaction_id` 与 `transaction_no`；返回形状与申赎一致：`{transaction, available_balance}`
- [ ] 入口 `POST /api/customer/transactions/deposit`（`DepositRequest{amount}`），客户标识由凭证推导，请求体里没有这个字段
- [ ] `alerting.TRANSACTION_TYPES` 加「充值」，并**重写 `alerting.py:93-95` 的注释**：类型分支只活在 7 条规则里（R011–R014、R016、R019、R020），其余 13 条只建在金额、笔数与时段上（R001–R010、R015、R017、R018），所以转账与充值都收得下
- [ ] **`_history_events` 读第三张表**（`alerting.py:166-203`）：新增 `_deposit_event()`（与 `_transfer_event()` 同形），并把自身那一行按「事件来自哪张表」排除——**漏了不会报错**，只会让窗口与累计类规则少算入金
- [ ] **ADR-0023**：充值独立建表（ADR-0019 的延续）+ 入金进风控而不是被受理侧拒收（ADR-0018 的延续）
- [ ] 断言：充值后余额按额度增加；金额为 0 / 负数被拒；没有资金账户被拒
- [ ] 断言：一笔充值**不写入** `fin_transaction`，但**照常过规则引擎**——60 万 → 命中 `R001`，预警列表里多出一条
- [ ] 断言：充值计入窗口与累计类规则的历史，形状同 `test_a_transfer_counts_toward_the_window_rules`

**实现落点：** `backend/app/order_acceptance/service.py`（`deposit`）、迁移 `0029_deposit`、`backend/app/db/models.py`（`Deposit`）、`backend/app/api/customer_transactions.py`（`POST /api/customer/transactions/deposit`）、`backend/app/risk_monitoring/alerting.py`（白名单、注释、`_history_events`）、测试 `backend/tests/test_customer_deposit.py`。

**验收：** 客户端充值一笔 → 余额按额度增加 → `risk1` 的预警列表出现对应预警。这条演示就是本 slice 的验收标准（spec 的 Solution）。

### 与转账的三处同构，照着 03 的写法做

充值的载体、受理与风控接入**与转账逐处同构**，实现时对照 `#03`（转账）与 `#04`（交易成为风控输入）的既有代码，不要另起一套：

- 受理侧把事实行与余额变动写在同一个会话里，由入海口提交它、再广播、最后过规则引擎——入海口返回 `Transaction | None`，充值这一侧返回 `None`。
- 流水号必须真写一列（转账的 `transfer_no` 就是这么来的），广播载荷里的 `transaction_no` 需要它。
- 预警**不填** `RiskAlert.transaction_ids`：那一列存的是 `fin_transaction` 的标识，三张表的 id 各自从 1 开始，混着填会让预警详情按 id 回查到另一笔毫不相干的交易。充值的金额与类型仍在命中依据里。
