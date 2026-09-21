# 01 — 可选项与合法区间的共享计算与读取端点

**What to build:** 客户经理在发起建议前要看得见「这位客户在这个方向下能选哪些产品、每只的金额区间是多少」。本份新增这个出口，并把它与发起受理要用的校验写成**同一个函数**——这是本 slice 最主要的实现约束。

新增 `GET /api/internal/customers/{customer_id}/operation-advice-options?direction=申购|赎回`。

候选池端点（`backend/app/api/suitability.py:27`）**不动**：候选池在 `CONTEXT.md` 里是与方向无关的合规事实（适当性硬过滤的结果），把方向过滤与金额区间并进去，会让它同时回答两个问题。

**Blocked by:** 无（候选池、资金账户与持仓读取均已就绪）

**Status:** implemented

- [x] 新增组装函数：给定客户与方向，返回可选项——申购 = 候选池 − 已持有；赎回 = 候选池 ∩ 已持有且份额大于零
- [x] 每项含 `product_code` / `product_name` / `product_type` / `risk_level` / `term_days` / `min_amount` / `max_amount` / `affordable`；赎回方向给 `max_shares` 而不是 `max_amount`
- [x] `max_amount` 走受理侧的 `purchase_cost`（`backend/app/order_acceptance/service.py:103`），**不另算费率**；`max_shares` 取当前持仓份额
- [x] 买不起（`purchase_cost(min_amount) > 可用余额`）的项 `affordable=false` 且**仍然出现**，不藏掉
- [x] 端点只对**客户经理且只对名下客户**开放（复用 `app/customer_scope.py` 的 `is_under_management`）
- [x] 方向非法 → 400，口径与 `backend/app/operation_advice/graph.py:53` 的 `ALLOWED_DIRECTIONS` 一致
- [x] 断言：申购方向不出现已持有产品；赎回方向只出现「候选池 ∩ 已持有」
- [x] 断言：买不起的产品带 `affordable: false` 而不是从列表里消失
- [x] 断言：非名下客户、理财顾问、风控专员调用被拒绝

**注意：** `affordable` 必须是后端算好的布尔。让前端复算费率就是第二套成交口径，差一分钱就会让下拉里出现一条注定被拒的产品——而它在审核页上看起来完全正常（`operation-advice-and-customer-trading` 的 #06 记着这一条）。

**实现落点：** 新增 `backend/app/operation_advice/options.py`（`advice_options` 组装可选项、`purchase_ceiling` 反解受理侧 `purchase_cost` 得金额上限、`serialize_advice_options` 负责呈现）、
新增端点 `GET /api/internal/customers/{customer_id}/operation-advice-options`（`backend/app/api/operation_advice.py`，与发起同一条路由前缀；角色门 `require_employee_role(ACCOUNT_MANAGER)` 与归属门 `advisory.access.ensure_can_view`）、
测试 `backend/tests/test_operation_advice_options.py`（8 条）。

候选池端点（`backend/app/api/suitability.py:27`）一个字没动。

### 几处写下来的决定

**方向的合法取值与文案不复制一份。** `ALLOWED_DIRECTIONS` / `UNKNOWN_DIRECTION_MESSAGE` 仍只有 `graph.py` 那一份，`options.py` 直接引用——两份常量就是两条口径，而这条要求恰恰是「口径一致」。那一份会在 02 里随选品整段一起收窄。

**上限是「再添一分钱就买不起」的那一分钱。** 反解 `purchase_cost` 之后先向下取整（向上取整会给出一个买不起的上限，前端把输入卡在它上面，每一条都会被受理拒绝），再往上补到真正买得起的最后一分：金额与手续费各自四舍五入，反解可能与真正的上限差一分。测试把这句话钉成了两条断言（上限买得起、上限加一分被受理拒绝）。

**`affordable` 在赎回方向恒为真。** 赎回没有余额门槛——卖出不需要先有钱，「选项成立」就是有份额可卖，而份额为零的持仓已被方向资格滤掉。字段仍然按统一形状给出：前端只读一个布尔，不为方向分叉。

**选不出产品时给空列表，不是错误。** 候选池为空、或池内的每一只都已持有（申购）／都没有持仓（赎回），端点的答案就是「没有」——空态有专门的两句文案，那两句属于表单。

**不适用于该方向的那一项不出现**（赎回没有 `max_amount`、申购没有 `max_shares`），而不是给一个空值：写一个不存在的事实与 `app.customer_assets.service._format_optional` 的既有口径相悖。

**赎回方向也读资金账户。** 赎回不花这笔钱，但受理赎回同样要求资金账户（成交金额要入账），缺账户时在这里就说出来，而不是给出一个一提交就失败的选项列表。

**受理侧的查找没有提前放进来。** 共享的那一份计算是 `advice_options`；02 接线时按 `product_code` 在它的结果里找，不把方向规则再表达一遍。这份 issue 的契约到此为止，查找函数与它的文案随 02 一起落地（否则它现在是一段没有调用者的代码）。
