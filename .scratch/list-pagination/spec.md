# 列表展示统一分页，交易流水归位交易模块

Status: ready-for-agent

前置：无——纯横切改造，所有被分页的接口均已实现，不依赖任何未完成的 slice。

**本 slice 新增一条 ADR（0024：统一 offset 分页契约），不推翻任何既有决定。**

## Problem Statement

**所有列表接口全量返回，前端零分页。** 盘点结果：后端 19 个列表接口全量 `.all()`、少数几个写死上限（历史会话 `LIST_LIMIT=100`、分析历史 `_HISTORY_LIMIT=50`），前端两端没有任何分页控件（`el-pagination` / `load-more` 均为 0 处），列表类型里没有 `total` / `page` 字段。列表随数据增长无界膨胀——最高危的是客户目录（全量客户 + 全量画像一起拉）。

**交易流水被放在资产模块。** `CONTEXT.md` 里「交易流水」归「资金与交易」分类，交易的写接口（申购/赎回/转账/充值）已挂在 `/api/customer/transactions/*`，但流水读接口却挂在 `/api/customer/assets/transactions`、前端在 `assets/` 目录、渲染在资产页底部。代码与领域模型偏离。

## Solution

**统一 offset 分页契约。** 所有「列表展示」统一走 offset 分页：响应 `data` 恒为 `{items, total, page, page_size}`，列表字段统一叫 `items`（弃用 `products`/`transactions` 等语义字段名），`page` 从 1 起、`page_size` 默认 20 / 上限 100；前端统一一个 `PaginationBar` 组件与一个 `usePagination`，交互统一数字分页。排序下推后端并保证稳定排序键。

**交易流水归位。** 流水读接口迁到 `/api/customer/transactions`（与写接口同域），前端迁到「交易」页（el-tabs 分「下单 / 交易流水」）。先重构（零行为变更）后分页——交易流水恰好是分页第一批的端到端验证对象。

## 访谈结论清单（grill-with-docs，2026-09-22，12 问）

### 分页 · 第一轮

| # | 决定 |
|---|---|
| Q1 | **offset 分页**，非 cursor：后台要跳页与总数，数据量级未到需 keyset 的程度；每个分页列表补稳定排序键。 |
| Q2 | **统一机制**，非各接口自理：二十余个接口各自加参数，必然在命名、响应形状与 `total` 口径上漂移。 |
| Q3 | **范围分四类**：第 1 类主数据列表全部纳入；第 4 类静态/配置/下拉/SSE 排除；第 2、3 类逐项判断。 |

### 分页 · 第二轮

| # | 决定 |
|---|---|
| Q4 | 契约 `{items, total, page, page_size}`，列表字段**统一叫 `items`**（弃语义字段名，前端才能复用 `Paginated<T>` 泛型）；`page_size` 默认 20 / 上限 100。 |
| Q5 | 前端统一 `PaginationBar`（封装 el-pagination，放 `packages/shared`）+ `usePagination`，交互统一数字分页，不引入无限滚动 / 加载更多。 |
| Q6 | 第 2 类（嵌套/详情内嵌）**保留现状**；第 3 类只把「独立列表资源」（历史会话、分析历史）升级真分页；`holdings` 持仓明细**保持嵌套不分页**（单客户量小、图表聚合需全量）。 |

### 分页 · 第三轮

| # | 决定 |
|---|---|
| Q7 | **机制 + 端到端并行**：第一批 = 统一机制 + 用「交易流水」做端到端验证（最难：三表扇入 + 内存排序 + 日期/类型筛选）。 |
| Q8 | **分批**：第一批只做机制 + 交易流水；其余接口拆后续 ticket 逐批推进，每份 ticket 都是「接口 + 对应页面 + 稳定排序下推」的完整闭环。 |
| Q9 | **新增 ADR-0024**（统一分页契约），含「排序下推后端」与「范围排除项」两条 consequence。 |

### 重构 · 交易流水归位

| # | 决定 |
|---|---|
| R1 | 读接口 `GET /api/customer/assets/transactions` → `GET /api/customer/transactions`（与写接口同域）。 |
| R2 | 前端「交易」页用 **el-tabs 分「下单 / 交易流水」**，不新增导航项。 |
| R3 | **先重构后分页**：拆两张 ticket，重构是零行为变更的搬移，分页在重构后的位置上做。 |

## User Stories

### 客户

1. As a 客户, I want to 在交易页看到我的交易流水并翻页, so that 下单与查账在同一处、流水多时不一次性加载
2. As a 客户, I want to 产品筛选、我的方案、我的建议都能翻页, so that 长列表可逐页浏览而不拖慢页面
3. As a 客户, I want to 历史会话能翻页回看, so that 会话多了仍能找到早先的对话

### 理财顾问

4. As a 理财顾问, I want to 审核队列与审核历史分页浏览, so that 待审内容多时不卡、能定位到具体一条

### 风控专员

5. As a 风控专员, I want to 预警、风控规则、风险关注列表分页, so that 数据多时排序与翻页保持一致

### 客户经理

6. As a 客户经理, I want to 名下客户列表与工单分页, so that 客户量大时仍能快速找到目标

### 开发者

7. As a 开发者, I want to 一套统一的分页契约与分页组件, so that 不每个接口重复发明分页、形状不再漂移

## Implementation Decisions

### 领域语言

`CONTEXT.md` **零改动**——分页是通用编程概念，不属于领域词汇表；「交易流水」词条定义已正确（「资金与交易」分类），本次重构是让代码对齐它，不是改它。

### 分页契约（后端）

- 新增统一分页依赖 / 工具（`paginate`）与统一响应 schema `PaginatedResponse`，形状恒为 `{items, total, page, page_size}`。
- 参数 `page`（1 起）+ `page_size`（默认 20、上限 100），由每个列表接口接收。
- `total` 用 count 查询得出；内存排序的列表（交易流水三表扇入）先合并去重再取 `total` 与切片。
- **排序下推后端**：每个分页接口必须有 `order_by` 稳定排序键。产品列表沿用 `product_code` 升序（ADR-0005）；其余列表补「时间倒序 + 表/行标识兜底」的稳定键。

### 分页契约（前端）

- `packages/shared/src` 新增 `PaginationBar`（封装 el-pagination，数字分页）+ `usePagination`（管理 `page`/`page_size`/`total` 状态与请求触发）。
- 补齐 customer 端的 query 拼装工具（与 internal 的 `api/query.ts` 对齐），统一把 `page`/`page_size` 拼进 query。
- 所有列表调用点的类型从语义字段（`products`/`transactions`）改为 `Paginated<T>`，字段统一 `items`。

### 真分页范围

纳入真分页的接口：交易流水、风控预警、风险关注、风控规则、客户目录、风险测评历史、投顾队列、投顾历史、客户方案、方案请求、工单、知识文档、操作建议（内部进度 + 客户我的建议）、历史会话、分析历史、产品筛选。

保留现状（不分页）：候选池（分页破坏「完整输入范围」语义）、持仓明细 `holdings`、详情内嵌列表（工单流转、留言、预警命中的关联交易与客户历史）、检索 `top_k`、分析结果 `truncated`、检查器 `slice(0,3)`、静态/配置/下拉/SSE 流式。

### 交易流水重构（分页第一批的前置）

- 后端读接口 `GET /api/customer/assets/transactions` → `GET /api/customer/transactions`；流水读 service（`list_transactions` 与 `_serialize_flow` 系列）从 `customer_assets` 迁出，落到与 `customer_transactions` 对应的读模块。
- 前端 `TransactionHistory` 从 `assets/` 迁到 `trading/`；资产页移除该卡片；交易页用 el-tabs 分「下单 / 交易流水」；`TransactionRecord`/`TransactionList`/`TransactionFilters` 类型与 `listTransactions` 一并迁到 `trading/`。
- 重构阶段**零行为变更**：搬完流水仍在交易页全量展示，接口语义不变。

## Testing Decisions

两个 seam 不变：seam 1 是后端 HTTP 层（`TestClient`），seam 2 是 Vue 组件挂载。

### Seam 1 — 后端 HTTP 层

- 每个分页接口断言：`items` 长度 ≤ `page_size`、`total` 为过滤后的总数、翻页不重不漏、`page` 越界返回空 `items` 且 `total` 不变。
- 交易流水分页断言：三表扇入后 `total` 正确、分页切片跨表不重不漏、排序键稳定（同秒记录按来源序号兜底）。
- 排序下推断言：排序字段生效于服务端（对「按等级/时间排序」的列表尤其要钉住翻页不乱序）。

### Seam 2 — Vue 组件挂载

- `PaginationBar` 渲染总数、翻页触发请求、禁用态正确。
- 每个接入分页的页面断言：翻页后表格内容更新、筛选条件保留、空页显示空态文案。
- 交易页 tab 断言：切换「下单 / 交易流水」互不干扰，流水表分页正常，四个下单表单行为不变。

## Out of Scope

- cursor / keyset 游标分页（Q1）
- 无限滚动 / 加载更多交互（Q5）
- 候选池、持仓明细、详情内嵌列表、检索 `top_k`、分析结果 `truncated`、检查器 `slice(0,3)` 的分页（Q6）
- 列表字段的兼容双读（`items` 与旧语义字段并存）——破坏性变更，不保留旧字段
- 静态/配置列表、表单下拉选项、SSE 流式消息的分页
- 子资源列表 `risk-rules/{id}/changes`、`suitability-decisions` 是否分页——实现时按单父资源下数据量逐项判断，默认保留现状

## Further Notes

- **排序下推是隐藏陷阱。** 现有预警列表是前端对全量结果排序，分页后若不同步改后端排序，会出现「只在本页内排序、翻页即乱」。每个 ticket 都要把「排序下推 + 稳定排序键」当作验收项，而不是顺手做。
- **字段名是破坏性变更。** `data.products`、`data.transactions` 等全部改为 `data.items`，前端类型与所有调用点同步改，不做兼容双读。这是一次性机械改动，且每个列表页本来就要接分页组件，正好一起改。
- **交易流水是分页契约的试金石。** 它是唯一「三表扇入 + 内存排序」的列表，`total` 口径与稳定排序键都在它身上第一次经受检验；它通了，其余纯 `.all()` 接口只是机械套用。
- **静态/配置/下拉列表不是分页对象。** 示例问题、agents 注册表、导航菜单、交易页的下拉产品/持仓选项、SSE 消息，是配置或交互，不是服务端列表资源——别被「v-for 渲染」误导去给它们加分页。
