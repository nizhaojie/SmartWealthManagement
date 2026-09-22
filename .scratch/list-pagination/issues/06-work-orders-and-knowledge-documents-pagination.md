# 06 — 工单与知识文档分页

**What to build:** 工单列表与知识文档列表各自分页；文档列表的筛选与「处理中」轮询在分页后保持正常。

**Blocked by:** 02 — 统一分页机制 + 交易流水端到端

**Status:** ready-for-agent

- [ ] `work-orders`、`knowledge/documents` 接口接收 `page`/`page_size`，返回 `{items, total, page, page_size}`
- [ ] 各列表补稳定排序键（时间倒序 + 标识兜底）
- [ ] `WorkOrdersPage`、`DocumentManagerPanel` 接 `PaginationBar`；文档列表的筛选与处理中轮询在翻页后仍正确
- [ ] 断言：翻页不重不漏、`total` 正确、筛选条件翻页保留

**实现落点：** `backend/app/api/work_orders.py`、`knowledge.py` 与 `app/work_order/service.py`、`app/knowledge/service.py`，`apps/internal/src/work-orders/WorkOrdersPage.vue`、`knowledge/DocumentManagerPanel.vue`，后端 HTTP 测试与前端 spec。

**验收：** 工单超过一页可翻页；文档列表筛选 + 翻页 + 处理中轮询协同正常。
