# 01 — 后端客户数据契约：回答携带结果表

**What to build:** 客服图的数据查询分支在「有行」时产出一份面向客户的结构化结果，随既有 `done` 帧送达；
客户侧解读文本收敛为「N 行 + 截断 + 口径」；列标签中文、剔除 `customer_id`、SQL 与视图名不外泄；回放模式下
客户侧不再采信员工口径的预置解读。**不新增 SSE 事件名、不新增端点、内部 `AnalyticsQueryResponse` 与内部气泡
零改动。**

**Blocked by:** 无（`customer-nl2sql` 已实现，代码在 `backend/app/agent/graph.py:103-138` 与
`backend/app/analytics/catalog.py`）。

**Status:** implemented

- [x] `data_answer` 契约：`backend/app/agent/schemas.py` 新增 pydantic 模型（`columns: [{key, label}]`、
      `rows: [[…]]`、`row_count`、`truncated`、`views`），`ChatResponse` 加**可选**字段；只在有行的数据查询
      出口非空
- [x] `answer_customer_data_question`（`backend/app/agent/graph.py:103-138`）把 analytics state 的
      `result.columns` / `result.rows` / `truncated` 带出来（`DataQueryTurn` 多一个字段）；`_data_query_material`
      与调试级留痕字段保持原样
- [x] 列标签：`ViewSpec`（`backend/app/analytics/catalog.py`）增 `column_labels`，四张 `va_my_*` 视图补齐中文
      标签；缺标签时**运行时回落列名**（不丢列）
- [x] 出客户契约时剔除 `customer_id` 列；`views` 用 `ViewSpec.label`（中文），不用 `va_*` 名称
- [x] 文本收敛：`_fake_customer_interpret`（`backend/app/analytics/interpretation.py:135-148`）去掉 `_row_lines`
      与 `_column_counts` 调用（这两个函数仍被员工/模型路径使用，**保留**），文案改为
      「为您查到 N 行数据（结果超出行数上限，已截断），已列在下表。数据口径：<视图口径>」
- [x] 三出口不带表且话术不变：`DATA_QUERY_FAILURE_MESSAGE` / `DATA_QUERY_EMPTY_MESSAGE` /
      `data_query_out_of_scope_message()`（`backend/app/agent/graph.py:73-89`）
- [x] 回放模式收口：`audience == CUSTOMER` 时不采信 `preset.interpretation`（`interpretation.py:66-70`），走确定性
      模板；预置 SQL 照旧使用
- [x] 两个端点共享同一 `ChatResponse`：`/api/customer/chat/messages` 与 `/stream` 的 `done` 帧形状一致
- [x] 断言：客户问「我持有哪些产品」→ `data_answer.columns` 的 `label` 全中文、无 `customer_id`、
      `len(rows) == row_count`；`answer` 不含英文列名、不含 `va_`
- [x] 断言：三出口 `data_answer` 为空；超 200 行时 `truncated == true` 且 `len(rows) == 200`
- [x] 断言（集成）：客户域四视图的列集合与 `column_labels` 的键集合一致
- [x] 断言：回放模式下客户问出 `ANALYTICS_PRESETS[0]` 的原句，文本走确定性模板且不含 `va_`

**实现落点：** `backend/app/agent/schemas.py`、`backend/app/agent/graph.py`、
`backend/app/analytics/catalog.py`、`backend/app/analytics/interpretation.py`；测试沿
`backend/tests/test_customer_data_query.py` 与 `test_chat_stream.py` 的既有手法。

**验收：** 客户登录后问「我持有哪些产品」，HTTP 响应（信封式与 SSE `done` 帧）里就有带中文表头的结构化结果；
同一问题的文本只剩行数、截断与口径；零行/失败/越界三种情况文本与今日逐字一致。
