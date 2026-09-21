# 04 — 交易成为风控的真正输入

**What to build:** 这一份 issue 修的就是需求里那句「现在的风控监测不起作用」。风控那一侧本来是完整的，缺的是输入端：交易事件在应用里没有任何真实触发点，种子数据又整批绕过了规则引擎。

做完这一份，项目上第一次有一个能演示的完整状态：**客户发起一笔 50 万转账 → 预警列表出现对应预警。**

**Blocked by:** 03 — 转账与客户侧流水合并读

**Status:** implemented

- [x] 客户的申购、赎回、转账**全部**走 `submit_transaction_event` 这一条路径，不新增第二条
- [x] 内部补录接口收窄：**只对风控专员开放**（现状是所有内部员工都能调）
- [x] 预警详情与列表增加来源标注（客户发起 / 内部补录），依据是**有无经办员工**，不新增字段
- [x] 种子里的历史交易改为**按时间正序逐笔**走同一个函数回放——**不另写批量脚本**，那正是今天这个 bug 的成因
- [x] 回放的预警时间戳**取该笔交易自己的时间**；规则求值的基准本来就是交易自身的时间，求值逻辑不需要改
- [x] 回放产生的历史预警**不做任何特殊化**：不标记、不隔离，靠时间倒序自然沉底
- [x] 写下并接受副作用：历史预警计入分级的历史计数，第一个在演示里做大额操作的客户很可能直接判**重度**——这是分级存在的理由，讲之前先想好台词
- [x] 断言：**客户发起一笔 50 万转账 → 预警列表出现对应预警**
- [x] 断言：非风控专员调用内部补录接口被拒绝（**新增护栏 7**，同时补进 `docs/adr/0009-compliance-guardrail-tests.md`）
- [x] 断言：广播通道不可用时，客户侧发起的交易与预警照常落库（既有用例换到客户侧入口上再跑一遍）
- [x] 断言：回放结果与逐笔调用同一函数的结果一致——把「回放不走旁路」这个事实钉住

**实现落点：** `backend/app/db/seed.py`（`_replay_historical_trades` / `_discard_previous_replay`）、
`backend/app/risk_monitoring/alerting.py`（`SOURCE_*` 与 `alert_sources`）、
`backend/app/risk_monitoring/alert_service.py`（列表与详情的 `source`）、
`backend/app/api/transaction_events.py`（`require_employee_role(RISK_OFFICER)`）；
测试 `backend/tests/test_transactions_as_risk_input.py`（新增），
`test_transaction_events_api.py` 与 `test_customer_transfer_and_merged_history.py`（改写既有断言）。

### 三处写下来的决定

**回放的经办员工取风控专员。** 种子那五笔历史成交是补录出来的既成事实（不经过适当性与
余额校验），而那是只有风控专员拿得到的口子，所以归属给它。来源标注于是认得出它们
（「内部补录」），与客户当场发起的交易（「客户发起」）形成对照——演示里两种标注同时可见。

**重复 seed 撤掉上一轮回放再重放**，而不是跳过已有行。跳过的话，本 issue 之前建的库
（那五笔交易从来没有过预警）永远补不上这道裂缝；而且命中依据是命中那一刻固化的快照，
在原行上改金额对齐会让实测值对不上。撤掉时连派生的工单一起撤：`source_alert_id` 是外键，
不撤会撞错，而且预警没了工单也没有来处。

**转账预警的来源按「客户发起」判定。** 依据是「有无经办员工」，而 `fin_transfer` 上没有
这一列（#03 交接的那一处）：转账只从客户侧受理进来，内部补录那条路必带产品、必然落在
`fin_transaction` 里，所以关联交易为空即客户发起。这条写进了 `alert_sources` 的 docstring。

护栏 7 的正文在 `docs/adr/0009-compliance-guardrail-tests.md` 里已是既成事实（随
「客户交易与操作建议的 spec、ADR 与词汇表」那份 docs 提交补入），`docs/roadmap.md` 的
分布表也已挂在 #04，本份无须再动它们。
