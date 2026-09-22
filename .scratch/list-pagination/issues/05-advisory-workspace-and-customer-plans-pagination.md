# 05 — 投顾工作台与客户方案分页

**What to build:** 投顾审核队列与审核历史、客户「我的方案」与「方案请求」各自分页。

**Blocked by:** 02 — 统一分页机制 + 交易流水端到端

**Status:** ready-for-agent

- [ ] `advisory/queue`、`advisory/history`、`advisory/plans`、`advisory-requests`（internal + customer 两端）接收 `page`/`page_size`，返回 `{items, total, page, page_size}`
- [ ] 各列表补稳定排序键（时间倒序 + 标识兜底）
- [ ] `AdvisoryWorkspace`（队列/历史）、`AdvisoryPlanPage`、`AdvisoryRequestList` 接 `PaginationBar`
- [ ] 断言：翻页不重不漏、`total` 正确

**实现落点：** `backend/app/api/advisory.py`、`advisory_request.py` 与 `app/advisory/queue.py`、`final.py`，`apps/internal/src/advisory/AdvisoryWorkspace.vue`，`apps/customer/src/advisory/`（`AdvisoryPlanPage.vue`、`AdvisoryRequestList.vue`），后端 HTTP 测试与前端 spec。

**验收：** 待审内容超过一页时队列可翻页、历史可翻页；客户方案与请求翻页正确。
