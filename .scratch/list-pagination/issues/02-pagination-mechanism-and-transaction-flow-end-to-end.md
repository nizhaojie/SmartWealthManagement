# 02 — 统一分页机制 + 交易流水端到端

**What to build:** 交易流水在「交易」页数字分页展示（总数 + 翻页），同时把整套统一分页机制落地——后端 `paginate` 工具与 `PaginatedResponse` schema、前端 `PaginationBar` 组件与 `usePagination`、customer 端 query 拼装工具。这是分页契约的端到端验证：交易流水是唯一「三表扇入 + 内存排序」的列表，`total` 口径与稳定排序键都在它身上第一次经受检验。

**Blocked by:** 01 — 交易流水归位到交易模块

**Status:** ready-for-agent

- [ ] 新增 **ADR-0024**：统一 offset 分页契约（`{items, total, page, page_size}`、`page` 1 起、`page_size` 默认 20 / 上限 100、列表字段统一 `items`、排序下推后端）
- [ ] 后端新增统一分页依赖/工具 `paginate` 与响应 schema `PaginatedResponse`，形状恒为 `{items, total, page, page_size}`
- [ ] 交易流水接口 `GET /api/customer/transactions` 接收 `page`/`page_size`（默认 20 / 上限 100），返回 `{items, total, page, page_size}`，`items` 为流水记录
- [ ] 交易流水分页正确：三表扇入后 `total` 为过滤后总数、跨表切片不重不漏、排序键稳定（`traded_at` 倒序 + 来源序号兜底，沿用既有 `records.sort` 的键）
- [ ] 前端 `packages/shared/src` 新增 `PaginationBar`（封装 el-pagination）+ `usePagination`
- [ ] customer 端补齐 query 拼装工具（与 internal 的 `api/query.ts` 对齐），统一把 `page`/`page_size` 拼进 query
- [ ] 前端 `Paginated<T>` 类型落地；交易流水调用点改用 `data.items`
- [ ] 交易流水 tab 接 `PaginationBar`：翻页更新表格、筛选保留、空页显示空态
- [ ] 断言：翻页不重不漏、`page` 越界返回空 `items` 且 `total` 不变、`page_size` 超上限被钳制

**实现落点：** `docs/adr/0024-*.md`、后端分页工具 + `PaginatedResponse`、`backend/app/api/customer_transactions.py`（GET 加参数）、`packages/shared/src`（`PaginationBar`、`usePagination`）、customer query 工具、`apps/customer/src/trading/`（分页接线）、两端测试。

**验收：** 交易流水超过一页时，翻页能看全所有记录、总数正确、同秒记录顺序稳定；机制（工具/schema/组件/composable）已就绪可供后续 ticket 复用。
