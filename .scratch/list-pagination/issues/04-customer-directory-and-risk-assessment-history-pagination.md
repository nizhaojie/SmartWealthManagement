# 04 — 客户目录与风险测评历史分页

**What to build:** 内部客户目录与单客户的风险测评历史各自分页。客户目录是最高危的一处——现状不仅 `select(Customer).all()`，还会把全量画像映射一起拉，分页改造要让画像映射按页内客户批量取，而不是整表全量。

**Blocked by:** 02 — 统一分页机制 + 交易流水端到端

**Status:** ready-for-agent

- [ ] `customers`、`customers/{id}/risk-assessments` 接口接收 `page`/`page_size`，返回 `{items, total, page, page_size}`
- [ ] 客户目录的 `list_customers` 分页改造：客户与画像映射都只取页内数据，`total` 为客户（过滤后）总数
- [ ] 客户目录与测评历史补稳定排序键（时间/标识兜底）
- [ ] `CustomerRelationsPage`、`CustomerListPanel`、`ProfileHistoryPanel` 接 `PaginationBar`
- [ ] `CustomerListPanel` 的前端关键字过滤与分页正确协同（过滤是服务端还是前端需与接口契约一致，不能只过滤当前页）
- [ ] 断言：翻页不重不漏、`total` 正确、客户目录不再全量拉画像

**实现落点：** `backend/app/api/customers.py`、`risk_assessment.py` 与 `customer_profile/service.py`，`apps/internal/src/customer-relations/`、`profile/`（`CustomerListPanel.vue`、`ProfileHistoryPanel.vue`），后端 HTTP 测试与前端 spec。

**验收：** 客户量超过一页时目录可翻页、画像数据只随页内客户加载；测评历史翻页正确。
