# 02 — 发起受理接手产品与金额 / 份额

**What to build:** 客户经理的发起请求第一次带上产品与金额（申购）或份额（赎回）。业务操作 Agent 由此从「选品 + 金额 + 理由」收窄为「只写理由」：图里的排序与选品整段消失，草案里的产品与数字**原样采用**请求给的那两个。

**Blocked by:** 01 — 可选项与合法区间的共享计算与读取端点

**Status:** ready-for-agent

- [ ] `backend/app/operation_advice/schemas.py:4-7` 的 `OperationAdviceRequest` 增加 `product_code`；`amount`（申购）与 `shares`（赎回）按方向二选一必填
- [ ] 受理校验放在 `generate_operation_advice` 里、编译图之前（与既有的 `_ensure_own_customer` 同一处，`backend/app/operation_advice/service.py:37-42`）：方向合法；产品在候选池内；方向资格成立（申购未持有、赎回已持有且份额大于零）；申购 `amount ≥ 起投` 且 `purchase_cost(amount) ≤ 可用余额`；赎回 `0 < shares ≤ 持仓份额`
- [ ] 校验调用 01 的**同一个函数**，不重写一遍
- [ ] 图里删除 `_ranked` / `_purchase_selection` / `_redemption_selection`（`backend/app/operation_advice/graph.py:105-150`）；`select_product` 变为「按 `product_code` 加载产品、采用给定的金额或份额」
- [ ] 三条错误文案重写（`graph.py:55-56`）：它们现在说的是「Agent 选不到」，而失败原因已经变成「发起人选的不合法」——`NO_CANDIDATE_MESSAGE` / `NOT_ENOUGH_BALANCE_MESSAGE` / `NO_HOLDING_MESSAGE`
- [ ] `biz_operation_advice_draft` 新增可空列 `redeemed_shares` + 迁移（`backend/app/db/models.py:855-896`）：**赎回时必填，申购为空**
- [ ] `build_reason` 与 `backend/app/operation_advice/reasons.py` **不动**（它们只吃产品要素与客户自己的数字，每一句仍可被顾问逐项核对）
- [ ] 断言：草案里的产品、金额 / 份额与请求里的完全一致——**Agent 不再改变它们**
- [ ] 断言：候选池外的产品被拒绝；已持有做申购被拒绝；未持有做赎回被拒绝；低于起投被拒绝；`purchase_cost(amount)` 超余额被拒绝；份额为零或超持仓被拒绝
- [ ] 断言：理由仍只引用候选池要素与客户自己的持仓 / 余额，不含配置比例与收益预测
- [ ] 改写 `backend/tests/test_operation_advice_draft.py` 中断言「Agent 从候选池里挑了哪只」的用例为「提交的那只被原样采用」

**注意：** 校验**不进** `submit_transaction_event`（ADR-0018 不变）——它仍然是既成事实的入海口。

**注意：** 护栏 1 在本份之后比之前更需要断言。把选品交给人的不是放开范围，反而是把范围检查从「Agent 顺手只挑池内的」变成「人可能挑池外的、必须明确拒绝」。
