# 04 — 客户经理的发起表单

**What to build:** 表单从「客户 + 方向」变成「客户 + 方向 + 产品 + 金额（申购）/ 份额（赎回）」。产品选项来自 01 的端点，买不起的显示但禁用。买不起的直接藏掉会让经理以为候选池里少了一只——这正是他要拿来跟客户解释的东西。

**Blocked by:** 02 — 发起受理接手产品与金额 / 份额（01 亦须完成）

**Status:** ready-for-agent

- [ ] `apps/internal/src/operation-advice/api.ts`：`startAdvice` 带上 `product_code` 与 `amount` / `shares`；新增取可选项的调用
- [ ] `apps/internal/src/operation-advice/CustomerAdviceSection.vue:84-103` 的表单：选完客户与方向后加载可选项（两个字段任一变化都要重取）
- [ ] 选项文案含五要素：产品名 + 代码 + 风险等级 + 期限 + 起投金额（`term_days` / `min_amount` 由 01 的端点给出）
- [ ] 买不起的选项 `disabled` 并注明「可用余额不足」
- [ ] 金额（申购）/ 份额（赎回）输入按 `min_amount` / `max_amount` 或 `max_shares` 设上下限，**前端不复算费率**
- [ ] 空态沿用既有两句文案：「该客户当前没有合规产品可选」/「可用余额不足以申购候选池内的任何产品」（`backend/app/operation_advice/graph.py:55-56`）
- [ ] 未选产品或未填金额 / 份额时提交被拦
- [ ] 组件测试：渲染可选项并显示五要素
- [ ] 组件测试：买不起的选项禁用且带原因
- [ ] 组件测试：两种空态各渲染对应文案，不留空白
- [ ] 组件测试：提交请求体含 `product_code` 与 `amount`（申购）/ `shares`（赎回）
- [ ] 组件测试：客户经理视角仍不存在放行 / 驳回入口（既有断言）
- [ ] 更新 `apps/internal/src/operation-advice/CustomerAdviceSection.spec.ts`（8 条）

**注意：** 前端只读后端给的 `affordable` 与区间，**不按方向过滤、不算买不买得起**。在客户端再做一次方向过滤就是选品规则的第二次表达，漂移的表现是「下拉里有这只产品，一提交被拒」，不会有断言失败。
