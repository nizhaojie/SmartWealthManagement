# 02 — 归档与客户历史：回看重绘同一张表

**What to build:** 会话归档多存一份结构化结果，客户历史详情**显式**把它带给客户（`data` 字段），使回看与实时
看到的是同一张表。归档的内容脱敏纪律不变（客户姓名照旧打码），但结构化结果**不过**文本正则脱敏。

**Blocked by:** `01-customer-data-answer-contract`（要先有那份结构化结果）。

**Status:** implemented

- [x] 新迁移 `0033`（head 现为 `0032`）给 `conversation_archive` 加一列（JSON、可空）存结构化结果；
      `backend/app/db/models.py` 的 `ConversationArchive` 同步加字段
- [x] `record_turn`（`backend/app/agent/archive.py:73-111`）增 `answer_data` 形参，只写进 assistant 行；user 行不变
- [x] 结构化结果**不过** `mask_pii`（三条文本正则只适用于自然语言文本）；`content` 的脱敏保持原样
- [x] `get_customer_session`（`archive.py:317-350`）显式把 `data` 带给客户：assistant 消息带结构化结果，无表时为
      `null`；**不**带 `sql`、`tool_calls`、`content_classification`
- [x] 内部端 `_serialize_message`（`archive.py:114-123`）**不动**——客户经理视角看不到这张表
- [x] 调用点接线：`run_customer_service_turn` 把这一轮的结构化结果传给 `record_turn`
      （`backend/app/agent/graph.py:610-620`）
- [x] 更新客户历史字段白名单断言（`backend/tests/test_customer_conversations.py:127-130`）为
      `{role, content, citations, created_at, data}`——改断言本身就是「这一步是刻意的」的记录
- [x] 断言：一轮数据问答后，历史详情 assistant 消息带 `data` 且形状与实时一致；同一会话里的知识问答那轮为
      `null`
- [x] 断言：内部端会话详情响应里不出现 `data`；越权/404 行为不变

**实现落点：** `backend/migrations/versions/0033_*.py`、`backend/app/db/models.py`、`backend/app/agent/archive.py`、
`backend/app/agent/graph.py`；测试沿 `backend/tests/test_customer_conversations.py` 与
`test_customer_data_query.py`。

**验收：** 客户问出一轮数据问题 → 打开「历史记录」→ 那一条回答下面就是同一张表；同一会话里问过产品要素的那轮
没有表。
