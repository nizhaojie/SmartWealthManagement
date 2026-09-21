# 02 — 发起受理接手产品与金额 / 份额

**What to build:** 客户经理的发起请求第一次带上产品与金额（申购）或份额（赎回）。业务操作 Agent 由此从「选品 + 金额 + 理由」收窄为「只写理由」：图里的排序与选品整段消失，草案里的产品与数字**原样采用**请求给的那两个。

**Blocked by:** 01 — 可选项与合法区间的共享计算与读取端点

**Status:** implemented

- [x] `backend/app/operation_advice/schemas.py:4-7` 的 `OperationAdviceRequest` 增加 `product_code`；`amount`（申购）与 `shares`（赎回）按方向二选一必填
- [x] 受理校验放在 `generate_operation_advice` 里、编译图之前（与既有的 `_ensure_own_customer` 同一处，`backend/app/operation_advice/service.py:37-42`）：方向合法；产品在候选池内；方向资格成立（申购未持有、赎回已持有且份额大于零）；申购 `amount ≥ 起投` 且 `purchase_cost(amount) ≤ 可用余额`；赎回 `0 < shares ≤ 持仓份额`
- [x] 校验调用 01 的**同一个函数**，不重写一遍
- [x] 图里删除 `_ranked` / `_purchase_selection` / `_redemption_selection`（`backend/app/operation_advice/graph.py:105-150`）；`select_product` 变为「按 `product_code` 加载产品、采用给定的金额或份额」
- [x] 三条错误文案重写（`graph.py:55-56`）：它们现在说的是「Agent 选不到」，而失败原因已经变成「发起人选的不合法」——`NO_CANDIDATE_MESSAGE` / `NOT_ENOUGH_BALANCE_MESSAGE` / `NO_HOLDING_MESSAGE`
- [x] `biz_operation_advice_draft` 新增可空列 `redeemed_shares` + 迁移（`backend/app/db/models.py:855-896`）：**赎回时必填，申购为空**
- [x] `build_reason` 与 `backend/app/operation_advice/reasons.py` **不动**（它们只吃产品要素与客户自己的数字，每一句仍可被顾问逐项核对）——赎回那一句有一处偏离，见下
- [x] 断言：草案里的产品、金额 / 份额与请求里的完全一致——**Agent 不再改变它们**
- [x] 断言：候选池外的产品被拒绝；已持有做申购被拒绝；未持有做赎回被拒绝；低于起投被拒绝；`purchase_cost(amount)` 超余额被拒绝；份额为零或超持仓被拒绝
- [x] 断言：理由仍只引用候选池要素与客户自己的持仓 / 余额，不含配置比例与收益预测
- [x] 改写 `backend/tests/test_operation_advice_draft.py` 中断言「Agent 从候选池里挑了哪只」的用例为「提交的那只被原样采用」

**注意：** 校验**不进** `submit_transaction_event`（ADR-0018 不变）——它仍然是既成事实的入海口。

**注意：** 护栏 1 在本份之后比之前更需要断言。把选品交给人的不是放开范围，反而是把范围检查从「Agent 顺手只挑池内的」变成「人可能挑池外的、必须明确拒绝」。

**实现落点：** 受理校验落在 `backend/app/operation_advice/options.py` 新增的 `resolve_advice_choice`（按 `product_code` 在 `advice_options` 的结果里找，再拿可选项里的 `min_amount` / `max_amount` / `max_shares` 判区间），服务入口只调它一次；
`ALLOWED_DIRECTIONS` / `UNKNOWN_DIRECTION_MESSAGE` 随选品整段从 `graph.py` 移到 `options.py`（否则 `graph` 与 `options` 互相 import）；
`graph.select_product` 按代码加载产品、用 `product_elements` 铺理由要用的产品要素，申购采用给定的金额、赎回采用给定的份额并由 `redemption_amount` 算出成交金额（另读一次客户当前的持仓份额，理由要写「从多少份里赎回多少份」）。
测试：`backend/tests/test_operation_advice_draft.py`（17 条，生成段整体改写 + 新增 6 条拒绝用例）、
`test_operation_advice_console.py` / `test_operation_advice_decision.py` / `test_end_to_end_customer_journey.py` 的发起调用改从可选项端点取输入、
`test_advisory_pipeline_content_types.py` 的载荷列集同步加上 `redeemed_shares`。

### 几处写下来的决定

**区间判定直接用可选项给的两个数，不重算费率。** `amount > max_amount` 与 `purchase_cost(amount) > 可用余额` 是同一件事：`purchase_ceiling` 反解的就是受理侧的那个函数，且它保证「上限买得起、上限加一分买不起」（01 的两条断言钉住了这一句）。受理侧再算一遍 `purchase_cost` 就是第二套口径，而两套口径差一分钱的表现正是「下拉里有这只产品，一提交被拒」。

**文案从三条变成七条。** 三条是改写（`NO_CANDIDATE_MESSAGE` / `NOT_ENOUGH_BALANCE_MESSAGE` / `NO_HOLDING_MESSAGE`，现在说的是发起人选的这只不合法），另外四条是「低于起投」「份额越界」「缺金额」「缺份额」——它们原来根本不出现，因为金额是 Agent 算出来的，不可能越界。

**赎回的理由跟着动了（与「`reasons.py` 不动」有一处偏离）。** 理由里的 `shares` 在改动之前**恒等于持仓总额**（只能全部赎回），交给发起人之后它变成「这次赎回多少」；原样不动的话，`redemption_reason` 的首句会把「客户持有 1200 份」印成「客户持有 600 份」——一句不成立的话，而它正是顾问要逐项核对的那类句子。因此只把那一句改成「客户当前持有 X 份；建议赎回 Y 份，赎回金额 Z 元」，`redemption_reason` 多收一个 `held_shares`（那一读由 `graph.select_product` 加载，是客户自己的事实，不经过模型）；`purchase_reason` 一个字没动。

**客户侧读到份额不在本份。** `decision.CUSTOMER_VISIBLE_ADVICE_FIELDS` 这一份没有加 `redeemed_shares`（那是 ADR-0016 里的显式动作），因此 US10「客户收到具体的赎回份额」要等 03——那一份才是客户侧按份额成交、因而必须把份额说清楚的地方。同理，接受侧这一份仍按当下的全部持仓成交。
