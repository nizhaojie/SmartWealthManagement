# 07 — 操作建议分页（客户建议进度 / 我的建议）

**What to build:** 内部「客户建议进度」与客户「我的建议」各自分页；客户「我的建议」按状态分组的展示在分页后保持。

**Blocked by:** 02 — 统一分页机制 + 交易流水端到端

**Status:** ready-for-agent

- [ ] `operation-advice`（internal `customers/{id}/operation-advice` 与 customer `operation-advice` 两端）接收 `page`/`page_size`，返回 `{items, total, page, page_size}`
- [ ] 各列表补稳定排序键（时间倒序 + 标识兜底）
- [ ] `CustomerAdviceSection`、`AdvicePage` 接 `PaginationBar`；「我的建议」按状态分组（待决定/已接受/已拒绝/已过期）展示保持
- [ ] 断言：翻页不重不漏、`total` 正确、分组不因分页错乱

**实现落点：** `backend/app/api/operation_advice.py`、`customer_operation_advice.py` 与 `app/operation_advice/console.py`、`decision.py`，`apps/internal/src/operation-advice/CustomerAdviceSection.vue`、`apps/customer/src/operation-advice/AdvicePage.vue`，后端 HTTP 测试与前端 spec。

**验收：** 建议超过一页可翻页；客户「我的建议」的状态分组与分页协同正常。
