# 08 — 历史会话与分析历史分页（第 3 类升级）

**What to build:** 把两个「写死上限」的独立列表升级为真分页——历史会话列表去掉 `LIST_LIMIT=100`、分析历史去掉 `_HISTORY_LIMIT=50`，改为 `page`/`page_size` 分页。会话详情内嵌的 `messages` 保持不分页（它是会话回看本身）。

**Blocked by:** 02 — 统一分页机制 + 交易流水端到端

**Status:** ready-for-agent

- [ ] `conversations`（internal + customer 两端）、`analytics/history` 接收 `page`/`page_size`，返回 `{items, total, page, page_size}`
- [ ] 移除写死上限：`app/agent/archive.py` 的 `LIST_LIMIT` 与 `app/analytics/service.py` 的 `_HISTORY_LIMIT`，改由分页参数控制
- [ ] 各列表补稳定排序键（时间倒序 + 标识兜底）
- [ ] `ChatHistoryDrawer`、`AnalyticsHistoryPanel` 接 `PaginationBar`
- [ ] 断言：翻页不重不漏、`total` 正确、历史会话不再被 100 条截断、分析历史不再被 50 条截断

**实现落点：** `backend/app/api/conversations.py`、`customer_conversations.py`、`analytics.py` 与 `app/agent/archive.py`、`app/analytics/service.py`，`apps/customer/src/chat/ChatHistoryDrawer.vue`、`apps/internal/src/analytics/AnalyticsHistoryPanel.vue`，后端 HTTP 测试与前端 spec。

**验收：** 会话超过 100 条仍能翻页看全、分析历史超过 50 条仍能翻页看全。
