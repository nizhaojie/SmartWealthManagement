# 所有列表接口统一走 offset 分页，列表字段统一叫 `items`

所有返回列表的接口现在都全量 `.all()` 返回，前端两端没有任何分页控件，列表会随数据增长无界膨胀。我们决定：所有「列表展示」统一走 **offset 分页**，响应形状恒为 `{items, total, page, page_size}`，列表字段统一叫 `items`（弃用 `products`/`transactions` 等语义字段名），`page` 从 1 起、`page_size` 默认 20 上限 100；前端统一一个 `PaginationBar` 组件与一个 `usePagination`。理由：二十余个列表接口若各自加 `page` 参数，参数命名、响应形状与 `total` 口径必然漂移；offset 足以满足后台跳页与总数需求，数据量级远未到需要 cursor 游标分页的程度。

## 决定

1. **统一 offset 分页契约。** 分页数据放在统一响应 `{code, message, data, trace_id}` 的 `data` 里，形状恒为 `{items, total, page, page_size}`；`page` 从 1 起，`page_size` 默认 20、上限 100。
2. **列表字段统一叫 `items`。** 弃用各模块自带的语义字段名（`products`、`transactions`…），前端才能用一个 `Paginated<T>` 泛型与一个 `usePagination` 复用到底。
3. **前端统一一个分页组件。** `PaginationBar` 封装 Element Plus 的 `el-pagination`，放 `packages/shared/src`（两端复用）；交互统一数字分页，不引入无限滚动 / 加载更多。
4. **排序下推后端，且必须有稳定排序键。** 分页列表在服务端 `order_by` 稳定排序，前端不再对整表排序。

## Consequences

- **排序从整表变成本页。** 现有预警列表是前端对全量结果排序，分页后必须把排序下推到后端，否则「按等级 / 时间排序」只会在当前页内生效、翻页即乱。
- **分页范围不是「所有 v-for」。** 候选池不拆（它是投顾助手的完整输入范围，分页会破坏「完整」语义）；详情内嵌列表（工单流转、留言、预警命中的关联交易与客户历史）与检索 `top_k`、分析结果 `truncated` 都保留现状；硬编码上限里只有「独立列表资源」（历史会话列表、分析历史）升级为真分页。
- **字段名是破坏性变更。** `data.products`、`data.transactions` 等全部改为 `data.items`，前端类型与所有调用点同步改，不做兼容双读。
- **产品列表的排序键不动。** `product_code` 升序（ADR-0005）已是稳定排序，直接沿用；其余列表补齐「时间倒序 + 表 / 行标识兜底」的稳定键。
