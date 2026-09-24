# 端到端演示脚本

这份脚本是**答辩材料**，不是测试夹具：它讲的是「怎么把 `operation-advice-and-customer-trading`
这条链路串成一个能讲的故事」，以及被追问时该指到哪一条断言。护栏与不变量由
`backend/tests/` 里的断言守着，本节最后一张表给出每个演示点对应的用例。

第五幕是另一条横切 slice（`customer-nl2sql`）的收口，不属上面那条链路：客户的智能客服
接上了 NL2SQL，用大白话查自己的账。

一句话主旨：**风控那一侧一直是完整的——规则、算子、分级、预警、工单都在；缺的是输入端。**
这个 slice 补的是「交易从哪来」：客户第一次能自己动钱，客户经理第一次能提建议，
而这两件事都从同一个交易事件入海口进风控。

## 一、准备

```bash
docker compose up -d --wait
cd backend && python -m app.db.setup   # 建表 + 种子 + 历史交易回放
pnpm install && pnpm dev               # 后端 8000、客户端 5173、内部端 5174
```

`start-all.bat` 等价于上面三步。**重跑 `python -m app.db.setup` 就是恢复初始演示状态**：
余额、持仓、历史交易与历史预警一起复位，且跑两遍结果一致。

- 客户端 http://localhost:5173 ｜ 内部端 http://localhost:5174 ｜ Swagger http://localhost:8000/docs
- 口令统一 `Test@1234`

## 二、账号与演示数据

| 身份 | 账号 | 演示用途 |
|---|---|---|
| 客户经理 | `manager1` 刘经理（名下 王守成 / 李思远 / 张衡） | 发起操作建议、开户 |
| 客户经理 | `manager2` 孙经理（名下 赵启明 / 钱远航） | 第三幕的发起人 |
| 理财顾问 | `advisor1` 陈顾问 | 审核队列、放行 / 驳回 |
| 风控专员 | `risk1` 周风控 | 预警列表、预警详情、工单处置 |
| 客户 | `zhangc3` 张衡 C3 可用余额 100 万 | 第二幕：50 万转账 |
| 客户 | `qianc5` 钱远航 C5 可用余额 500 万，持有玉衡进取 200000 份 | 第三幕：建议链路 |
| 客户 | `wangc1` 王守成 C1 可用余额 **2000** | 第四幕：余额不足被拒绝（刻意给少的）；第五幕：C1 只筛得出 R1 |
| 客户 | `lisic2` 李思远 C2 | 第五幕：C2 筛得出 R1/R2 两档 |

**上台前必须知道的三件事：**

1. **五位种子客户的风评都停在 2018–2023 年（已过期）。** 候选池与产品筛选把过期当熔断，
   会回「风险评测已过期，画像权限已冻结，请重新评估」；而交易受理只看「有没有做过风评」
   （Q18），不看有效期。所以凡是要用到候选池的演示（产品筛选、发起建议），先让那位客户
   **重做一次风评**——这也是演示的第一步。
2. **余额的初始值来自种子，应用里有充值入口。** 余额不足不用换客户重来：充值即可当场
   自救（第四幕）。
3. **种子里那五笔历史成交在 `seed` 时被逐笔回放过**，产生的历史预警标注「内部补录」、
   按时间倒序自然沉底；演示中当场发起的交易标注「客户发起」，永远排在最上面。列表里同时
   有「监测一直在跑」和「现在是活的」两种证据。

## 三、第一幕：这块牌子以前为什么是空的（约 30 秒）

内部端用 `risk1` 登录 → **风控监测 → 预警列表**：列表里已经有若干条 2018–2022 年的历史预警。
点开最早的一条，看详情页的**来源：内部补录**（旁边一句「未经适当性与余额校验」）。

> 台词：「风控这一侧是完整的：20 条规则、算子、分级、预警、工单，测试也齐备。问题在于
> 应用里没有任何一笔交易经过它——唯一的入口是一个需要员工身份的内部接口，而种子数据过去
> 是直接写库的，绕过了规则引擎。所以『风控不起作用』不是判断不对，是没有输入。」

## 四、第二幕（本 slice 的验收标准）：客户直接发起一笔 50 万转账 → 预警列表出现对应预警

1. **客户端**用 `zhangc3` 登录 → **交易**：可用余额 `1,000,000.00`。
2. 在「转账」里填：收款人姓名 `李四`、收款人账号 `6222020200112233445`、金额 `500000.00`
   → **确认转账** → 页面回「转账成功，流水号 `TR…`，收款人 李四」，可用余额变成 `500,000.00`。
3. （顺带看一眼）**我的资产 → 交易流水**：这一行转账排在种子里那笔历史申购的前面（按成交
   时间倒序），它没有产品名、有收款人——两类记录真的合成了同一张流水。
4. **内部端**用 `risk1` 登录 → **风控监测 → 预警列表**：最上面一条「大额交易」，等级**重度**，
   命中规则 4~5 条（`R001` 单笔大额、`R003` 同日累计、`R004` 七日累计、`R005` 整数倍大额；
   非工作时间演示还会多一条 `R017`）。
5. 点「查看」进**预警详情**：
   - **来源：客户发起**（依据是关联交易没有经办员工，不是新增的字段）；
   - **命中依据**：一行一条规则，带判定字段、实测值与阈值；
   - **关联交易**：「没有关联的交易记录」——转账没有 `fin_transaction` 那一行，
     金额与类型仍在命中依据里；
   - **该客户的历史预警**：一条 2020 年的（回放出来的）。
6. **重度预警的来历（这段是必讲的台词）：**

   > 「这笔转账**单看是中度**：它命中 4 条规则，多规则交叉、此前没有记录就是中度。
   > 但它叠加了这位客户的历史预警记录，于是判**重度**——分级看的就是这两件事：这一笔
   > 命中了多少条，以及这位客户被记录过什么。那条历史预警来自种子回放，是我们刻意留下的，
   > 不是脏数据：它证明这套监测在历史数据上也在跑。」

7. **处置**：在详情页填处置理由（如「客户短期大额转出，需要核实收款方」）→ **派生工单**
   → 进入工单详情 → **接单**（理由）→ **办结**（理由 + 结论）；流转留痕里三次流转都有
   处置人与非空理由。回工单管理列表能看到它已办结。

## 五、第三幕：一条建议走完全程（客户经理发起 → 顾问放行 → 客户决定 → 成交 → 风控看到）

用 `manager2` + 客户 `qianc5`，方向选**赎回**：这位客户持有玉衡进取 200000 份，
Agent 会给出该持仓的全部成交金额 `500,000.00` 元——正好是一笔会被规则引擎命中的操作。

1. **先补风评**（原因见「上台前必须知道的三件事」）：客户端 `qianc5` 登录 → **产品筛选**
   → 提示「风险评测已过期，画像权限已冻结，请重新评估」→ 侧栏 **风险测评** → 全选最后一档
   → 提交，等级 `C5` → 回产品筛选，5 只在售产品全部可见。
2. **发起**：内部端 `manager2` 登录 → **客户关系 → 操作建议**：客户选「钱远航」、
   建议方向选「赎回」→ **发起建议** → 提示「已发起，等待理财顾问审核」；下面的进度表出现
   一行：玉衡进取基金 / 赎回 / 500,000.00 / 审核进度「待审」/ 客户决定「—」
   （未放行时客户决定是**空**，因为客户此刻读不到这条建议）。
   > 台词：「产品与金额是经理选的，Agent 只写理由（ADR-0021）——选品权在发起人手里，
   > 而理由要拿去过审核，所以它必须是能审的东西。一次只给一个产品一个方向，金额必填。」
3. **放行**：内部端 `advisor1` 登录 → **投顾助手 → 待审核**：队列里同时有方案与操作建议，
   每一行带**类型**标注，摘要按类型给。点这条操作建议的「查看」→ **审核操作建议**页：
   内容类型「操作建议」，载荷只有**一个产品、一个方向、一个金额、一条理由**
   （没有候选池、没有配置建议——那是方案特有的字段）。驳回理由留空时「驳回」不可点；
   直接点**放行**。
4. **客户看到并决定**：客户端 `qianc5` 的侧栏「我的建议」出现**待决定角标**→ 页内
   「待客户决定」组：产品、赎回 500000.00 元、理由、**有效期至（7 个自然日）**、免责声明
   → 点**接受** → 这一条移入「已接受」组并带上决定时间。
   - 想同时演示拒绝：再发起一条建议、放行、点**拒绝** —— 状态进「已拒绝」，**不产生交易**。
   - 想演示接受失败：接受那一刻才跑受理校验，所以「先让余额不够，再接受」就是一条现成的
     失败路径（建议的金额是固定的，把余额转走之后它就不够了）。失败渲染的是受理侧原文
     （「可用余额不足，还差 X 元」），建议**仍留在待客户决定**——补足条件后可以再接受一次，
     不存在「已接受但成交失败」这个状态。
5. **成交之后**：客户端 **我的资产** 里玉衡进取那笔持仓消失（份额归零不再是「持有中」），
   可用余额增加 `492,500.00`（500,000 扣 1.5% 手续费）。
6. **风控看到同一条链路的另一端**：`risk1` → 风控监测 → 预警列表，最上面一条就是这笔赎回
   产生的预警（`R001/R003/R004/R005/R020`，**重度**）。
   > 台词：「建议只是把『这笔要不要做』这步变得可审核；成交仍然走客户直接交易那一套受理
   > 校验，也仍然从**同一个**交易事件入海口进风控——三条路径只有一条。」

## 六、第四幕：三道拒绝，各归各位

1. **余额不足被拒 → 充值 → 同一笔转账成功**：客户端 `wangc1` 登录 → 交易：可用余额
   `2,000.00` → 转账 `5000.00` → 「可用余额不足，还差 3000.00 元」。看「我的资产」的流水：
   **没有**任何新记录，校验全部在写库之前。
   → 回交易页**充值** `5000.00`：余额变成 `7,000.00`，流水里多出一条「充值」。
   → 再发同一笔转账 `5000.00` → 「转账成功」，余额变成 `2,000.00`。
   > 台词：「余额不足在这里不是死路——种子给的是初始值，应用里有充值入口。当场充一笔，
   > 同一笔转账就走通了：这一屏讲的是『拒绝 → 自救 → 成功』，不是换一位客户重来。」
   - 申购那条路径的余额不足（C1 买天枢货币基金 5000，还差 `3012.50` 元手续费也一起算）
     在同一位客户身上要先把风评补上才点得到——交易页的在售产品同样受候选池的过期熔断
     影响（见第一幕第 1 条）；这条路径的断言是
     `test_a_purchase_beyond_the_available_balance_is_rejected`。
2. **越级**：`wangc1` 是 C1，产品筛选里**根本看不到** R2 以上的产品（第一道门在候选池的
   硬过滤）。受理层还会再守一次：拿一份 C1 凭证去申购 R4 产品，回
   「产品风险等级高于你的风险承受等级」——界面上看不到越级产品，所以这条用 Swagger 演示
   一发即可（`POST /api/customer/transactions/purchase`）。
3. **未做过风评**：内部端 `manager1` → 客户关系 → **开户**，为客户经理新开一位客户
   （姓名 / 账号 / 分层 / 收入区间 / 资产规模 / 投资经验），把初始密码设为 `Test@1234`
   → 客户端用新账号登录：
   - **产品筛选**提示「暂无风险测评记录」，**交易**页的在售产品也读不到——适当性门禁先于交易；
   - 侧栏 **风险测评** → 16 题 → 提交，等级出来；
   - 回产品筛选：产品清单出现，交易页可以选品下单。
   > 台词：「受理层的拒绝文案是『请先完成风险测评』，不是『风险等级不足』——开户时写下的
   > C1 是占位而不是结论。客户做完风评，同一笔交易当场就能走通。这一屏演示到『门禁打开』
   > 为止：新开户客户的资金账户在开户时就建出来了，可用余额为 0（余额 0 是开户的起点，充值
   > 入口见第 1 条），此时下单回的是『可用余额不足』——没钱与没有资金账户是两件事，后者的话，
   > 资产页上的『—』
   > 说不清是哪一种。最后那一步成交由
   > `test_the_same_customer_can_trade_after_taking_the_assessment` 钉住。」

## 七、第五幕：客户用大白话问自己的账（`customer-nl2sql`）

客户端用 `wangc1` 登录 → **智能客服**。这一屏以前只会查知识库，现在同一句大白话也能查自己的
账——查的是**客户域语义视图**，行级条件内建为「只出凭证客户本人的行」。三句问话各演一面。

1. 问**「我持有哪些产品」** → 回答是一段文本，数字直接写在里面（产品代码、份额、市值），
   **没有引用角标**。
   > 台词：「引用是知识检索的契约——有出处才敢说。数据回答的依据是查询本身：这条答案是一条
   > SELECT 跑出来的，跑的是锁死到本人那一行的视图，所以它不需要角标，也不许退到知识库去
   > 凑一段泛泛之谈。」
2. 问**「有什么适合我的风险等级的产品」** → 产品清单，**只按产品代码排序**：王守成是 C1，
   清单里只有 R1；换 `lisic2` 李思远（C2）看得到 R1/R2 两档，顺序仍是产品代码。
   > 台词：「这不是推荐。等级结论就是他自己可见视图里的一列，筛的是客观条件；清单只筛不排序、
   > 按产品代码排——不评分、不按收益或费率排（护栏 4）。排序与理由要到投顾那一侧才有。」
3. 问**「我的画像标签是什么」** → 白名单外语术：明说不在可查范围，并把能查的列出来
   （持仓明细、交易流水、资金账户余额、风险承受等级、产品要素）。
   > 台词：「画像标签在客户可见视图的边界外，所以它拿到的不是一段编出来的回答，而是一句
   > 『不在我能查询的范围内』——比知识库兜底更诚实。」
4. **零行与失败是两句话**：查不到数据是「没有查到符合条件的数据」（事实），查询失败或超时是
   「暂时查不了，请稍后再试，或到资产页查看」并落一条降级留痕。想现场看降级那一面，把执行
   超时调到极小再问第 1 句即可——**任何一条出口都不会回退到知识检索**。

## 八、收尾与重置

- 重新执行 `cd backend && python -m app.db.setup` 即可回到本节各幕的起点（余额、持仓、
  历史交易与历史预警一起复位）；重复执行两次的结果完全一致。
- 事件总线（Redis）不可用时不影响演示的正确性：交易与预警照常落库，只是广播与订阅方
  （风险关注、SSE 推送）不生效。

## 九、被追问时指到哪条断言

| 演示点 | 断言 |
|---|---|
| 50 万转账 → 预警列表出现对应预警 | `tests/test_transactions_as_risk_input.py::test_a_customer_transfer_shows_up_in_the_alert_list` |
| 转账也过规则引擎、且进历史回溯 | `tests/test_customer_transfer_and_merged_history.py::test_a_transfer_reaches_the_rule_engine`、`::test_a_transfer_counts_toward_the_window_rules` |
| 客户侧流水一定含转账（`INNER JOIN fin_product` 那个漏点） | `tests/test_customer_transfer_and_merged_history.py::test_the_merged_history_lists_purchase_redemption_and_transfer_together` |
| 回放走的是与实时同一个函数（防「再写一个批量脚本」） | `tests/test_transactions_as_risk_input.py::test_seed_replays_every_historical_trade_through_the_same_function`、`::test_seeding_twice_leaves_the_same_history` |
| 重度预警的来历（历史预警计入分级） | `tests/test_transactions_as_risk_input.py::test_a_replayed_alert_counts_toward_grading_history` |
| 未放行的建议客户侧读不到；客户经理放不了行 | `tests/test_operation_advice_decision.py::test_an_unreleased_advice_is_invisible_to_the_customer`、`::test_only_the_advisor_can_release_an_advice` |
| 接受即成交、走同一个入海口并过规则引擎 | `tests/test_operation_advice_decision.py::test_accepting_an_advice_strikes_a_trade_through_the_rule_engine` |
| 余额不足被拒绝 | `tests/test_customer_purchase_and_redemption.py::test_a_purchase_beyond_the_available_balance_is_rejected`、`tests/test_customer_transfer_and_merged_history.py::test_a_transfer_beyond_the_available_balance_is_rejected` |
| 充值让余额有了入口；大额入金进风控 | `tests/test_customer_deposit.py::test_a_deposit_adds_to_the_available_balance`、`::test_a_deposit_reaches_the_rule_engine` |
| 越级被拒绝 | `tests/test_customer_purchase_and_redemption.py::test_an_overgrade_purchase_is_rejected` |
| 未测评被引导；做完风评同一笔交易能走通 | `tests/test_customer_purchase_and_redemption.py::test_a_customer_who_never_took_the_assessment_is_asked_to_take_one`、`::test_the_same_customer_can_trade_after_taking_the_assessment` |
| 客户自助发起的交易没有经办员工（来源不加字段） | `tests/test_customer_purchase_and_redemption.py::test_a_customer_initiated_trade_has_no_operator`、`tests/test_transactions_as_risk_input.py::test_a_customer_trade_is_marked_as_customer_initiated` |
| 内部补录只对风控专员开放（ADR-0009 护栏 7） | `tests/test_transaction_events_api.py::test_backfilling_a_transaction_is_reserved_for_the_risk_officer` |
| 广播通道不可用时交易与预警照常落库 | `tests/test_transactions_as_risk_input.py::test_a_broken_bus_does_not_stop_a_customer_trade_or_its_alert` |
| 五个 Agent 各自被打到真实链路上（含本 slice 的业务操作 Agent） | `tests/test_end_to_end_customer_journey.py::test_full_customer_journey_for_both_personas` |
| 新开户客户的资金账户在开户时就有了（余额 0），下单回的是余额不足 | `tests/test_customer_onboarding.py::test_a_newly_opened_customer_has_a_funding_account_with_no_money`、`::test_a_freshly_opened_customer_is_short_of_balance_not_missing_an_account` |
| 目标配置是一组比例：合计不是 100 一律拒绝（开户与手工修正两条路径） | `tests/test_customer_onboarding.py::test_a_target_allocation_that_does_not_total_one_hundred_is_rejected`、`::test_the_target_allocation_cannot_be_smuggled_in_through_the_tag_correction` |
| 第五幕：客户问「我持有哪些产品」拿到本人持仓的文本（无角标、不碰知识检索） | `tests/test_customer_data_query.py::test_customer_asks_for_own_holdings_and_gets_her_own_numbers` |
| 第五幕：产品清单只筛不排序、按产品代码排、无推荐话术（护栏 4 的客户段） | `tests/test_customer_data_query.py::test_product_screening_filters_by_own_level_and_sorts_by_product_code_only` |
| 第五幕：白名单外得到边界话术，不是知识库兜底 | `tests/test_customer_data_query.py::test_question_outside_the_whitelist_gets_the_boundary_message`、`::test_employee_side_views_are_not_in_the_customer_candidate_set` |
| 第五幕：零行是事实、失败是降级（并留痕），两者话术可区分 | `tests/test_customer_data_query.py::test_zero_rows_answers_the_fact_while_failure_answers_the_degradation`、`::test_failed_query_degrades_with_a_trace_and_never_falls_back` |
| 第五幕：客户段护栏——写类与伪造身份被拒、员工域取不到行、注入改不了范围（护栏 3） | `tests/test_customer_data_query.py::test_malicious_queries_are_rejected_on_the_customer_path`、`::test_a_write_class_query_cannot_reach_the_customer_ledger`、`::test_the_employee_domain_stays_out_of_reach_from_the_customer_path`、`::test_a_forged_customer_id_cannot_widen_the_row_scope` |
| 第五幕：归还连接前清掉客户身份，未设置身份时客户域零行 | `tests/test_analytics_query.py::test_customer_identity_is_reset_before_the_connection_returns_to_pool` |
