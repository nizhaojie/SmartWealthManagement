# 01 — 可选项与合法区间的共享计算与读取端点

**What to build:** 客户经理在发起建议前要看得见「这位客户在这个方向下能选哪些产品、每只的金额区间是多少」。本份新增这个出口，并把它与发起受理要用的校验写成**同一个函数**——这是本 slice 最主要的实现约束。

新增 `GET /api/internal/customers/{customer_id}/operation-advice-options?direction=申购|赎回`。

候选池端点（`backend/app/api/suitability.py:27`）**不动**：候选池在 `CONTEXT.md` 里是与方向无关的合规事实（适当性硬过滤的结果），把方向过滤与金额区间并进去，会让它同时回答两个问题。

**Blocked by:** 无（候选池、资金账户与持仓读取均已就绪）

**Status:** ready-for-agent

- [ ] 新增组装函数：给定客户与方向，返回可选项——申购 = 候选池 − 已持有；赎回 = 候选池 ∩ 已持有且份额大于零
- [ ] 每项含 `product_code` / `product_name` / `product_type` / `risk_level` / `term_days` / `min_amount` / `max_amount` / `affordable`；赎回方向给 `max_shares` 而不是 `max_amount`
- [ ] `max_amount` 走受理侧的 `purchase_cost`（`backend/app/order_acceptance/service.py:103`），**不另算费率**；`max_shares` 取当前持仓份额
- [ ] 买不起（`purchase_cost(min_amount) > 可用余额`）的项 `affordable=false` 且**仍然出现**，不藏掉
- [ ] 端点只对**客户经理且只对名下客户**开放（复用 `app/customer_scope.py` 的 `is_under_management`）
- [ ] 方向非法 → 400，口径与 `backend/app/operation_advice/graph.py:53` 的 `ALLOWED_DIRECTIONS` 一致
- [ ] 断言：申购方向不出现已持有产品；赎回方向只出现「候选池 ∩ 已持有」
- [ ] 断言：买不起的产品带 `affordable: false` 而不是从列表里消失
- [ ] 断言：非名下客户、理财顾问、风控专员调用被拒绝

**注意：** `affordable` 必须是后端算好的布尔。让前端复算费率就是第二套成交口径，差一分钱就会让下拉里出现一条注定被拒的产品——而它在审核页上看起来完全正常（`operation-advice-and-customer-trading` 的 #06 记着这一条）。
