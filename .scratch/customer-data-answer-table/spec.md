# 客户端数据查询的结果表（智能客服的 NL2SQL 回显换成表格）

Status: ready-for-agent

前置：`customer-nl2sql`（已实现，客服图的「数据查询」分支 + 四张客户域语义视图，见 ADR-0025）、
`analytics-chat-ui`（已实现，内部数据分析的「口径解读 + 结果表」形态）、
`foundation-and-customer-service-slice` / `session-renewal`（已实现，客户历史记录复用会话归档，见 ADR-0015）。

**本 slice 新增 ADR-0028**（客户数据回答携带结果表），并**推翻 ADR-0025 的一条既有决定**。
`CONTEXT.md` 零改动（呈现层的形状不进 glossary）。

## 本 slice 改到的既有决定

| 被改的决定 | 出处 | 改法 |
|---|---|---|
| 「结果以文本解读送达，不扩展 SSE 表格帧」 | `docs/adr/0025-customer-data-query-reuses-the-analytics-chain.md` Consequences | 由 **ADR-0028** 推翻：有行时 `done` 帧携带客户侧结构化结果，文本收敛为口径与行数 |
| 「表格帧 / SSE 协议改动在 Out of Scope（Q5A）……表格渲染另开 spec」 | `.scratch/customer-nl2sql/spec.md` Out of Scope 第一条 | 本 slice 就是那份 spec |
| 「客户侧任何改动在 Out of Scope」 | `.scratch/analytics-chat-ui/spec.md` Out of Scope | 本 slice 越过它；内部端 `el-table` 与 `AnalyticsQueryResponse` **一个字段不动** |
| 「详情只给 role / content / citations / 时间」 | ADR-0015 决定 4 | 客户历史详情**显式**新增一个 `data` 字段——ADR-0016 的手法：要送达客户得显式加一次，并确认它落在客户可见视图内 |
| 「内容沿用归档的脱敏版」 | ADR-0015 决定 5 | 结构化结果不过 `mask_pii`（它是给自然语言文本用的）；客户姓名打码的代价继续成立，只是不适用于数据列 |
| 第七节台词「回答是**一段文本，数字直接写在里面**（产品代码、份额、市值）」 | `docs/demo-script.md:166-170`、断言表 `:214-219` | 由 #04 改写为「文本 + 结果表」 |

## Problem Statement

**客户拿到的数据回答是一件“念表格”的句子。** 客户侧解读为确定性模板（Q5A 的后果：不走模型，否则模型
会编造结果里没有的数字），而模板的构成是 `_row_lines`（每一行的每个字段都念一遍）+ `_column_counts`
（低基数计数）——`backend/app/analytics/interpretation.py:104-148`。列名来自客户域视图，全英文
snake_case（`backend/migrations/versions/0030_customer_domain_semantic_views.py:44-152`），于是客户读到
`为您查到 3 行数据。按 product_type：固收 2 行、权益 1 行。product_name 为 稳健增利，market_value 为
120000；…`。

**这个形态本该更早被表取代。** 内部数据分析页是「口径解读 → 结果表 → 可折叠 SQL → 元信息行」的固定次序
（`apps/internal/src/analytics/AssistantResult.vue:22-31,59-88`），客户侧没有等价物。拦路的不是技术，是一条
已落地的决定：ADR-0025 把「不扩展 SSE 表格帧」写进了 Consequences，`customer-nl2sql` 的 Out of Scope 也把
表格渲染推给了「另开 spec」。

**一条连带影响必须先钉住**：客户「历史记录」读的是同一份归档文本（ADR-0015），一旦文本收敛，回看里那一轮
就只剩「N 行 + 口径」——实时有表、回看无表，信息量差一个量级（Q8）。

## Solution

**有行时，客户侧数据回答携带一份结果表。** `done` 帧的 `ChatResponse` 新增可选 `data_answer`
（`columns: [{key, label}] / rows / row_count / truncated / views`），前端在文本播完后渲染结果表；文本收敛为
「N 行 + 截断提示 + 数据口径」。零行、失败/超时、白名单外三种出口不带表，话术一字不改。

**表只可能来自客户域语义视图。** `views` 给中文 label（客户不认 `va_my_holdings`），`customer_id` 列在出
客户契约时剔除，SQL 不给客户，英文列名不出现在客户可见的任何地方。

**归档与实时是同一张表。** `conversation_archive` 增一列存结构化结果，客户历史回看复用同一个渲染组件。

**回放模式顺带收口**：客户侧不采信员工口径的预置解读文本（预置里写着内部视图名），预置 SQL 照旧使用。

## 访谈结论清单（grill-with-docs，2026-09-27，三轮共 15 问）

### 第一轮

| # | 决定 |
|---|---|
| Q1 | **结构化结果走既有 `done` 帧（A）**：扩展 `ChatResponse` 而非新增 SSE 事件或 REST 端点。前端 `parseFrame` 的非 `done` 分支会把新事件当 delta，且表没有“边跑边出”的语义。代价明认：前端 `api.spec.ts` 的深度相等断言要改。 |
| Q2 | **文本收敛（A）**：逐行明细与低基数计数从客户文本里去掉，文本只留「N 行 + 截断 + 口径」，表格成为数据的唯一出处。顺带修掉“把英文列名当人话念给客户”的既有毛病。 |
| Q3 | **列标签由后端给（A）**：标签进 `catalog.py` 的 `ViewSpec`（视图知识同处一处），配测试断言「客户域四视图的列集合 == 标签键集合」；缺标签时运行时回落英文列名（不丢列），测试期必须红。不做前端映射（无护栏）、不做 LLM 中文别名（标签押在模型上）。 |
| Q4 | **原生 `<table>`（A）**：对齐客户侧三处既有表格的形态与令牌，不引入 `el-table`。要的是内部数据分析的**显示效果**（解读 + 表 + 截断提示 + 行数），不是同一个组件。 |
| Q5 | **客户侧的附加物（A）**：只给「解读 + 表 + 截断提示 + 共 N 行」，不给 SQL、不做 CSV 导出；行数上限沿用后端 200、超时 5s，不新增客户专用参数。 |
| Q6 | **三种出口保持文本（A）**：零行、失败/超时、白名单外都不出表。零行与失败必须可区分是既定的品味线，一张空表会把两者在观感上抹平。 |
| Q7 | **文档产出（A）**：新增 ADR-0028（记录为什么推翻 ADR-0025 的「不扩展 SSE 表格帧」，并钉住「结构化结果只来自客户域视图」）；新 spec slug `customer-data-answer-table`；`CONTEXT.md` 一句不改。 |

### 第二轮

| # | 决定 |
|---|---|
| Q8 | **归档也存结构化结果（B）**：`conversation_archive` 增列，客户历史回看重绘同一张表；不做「归档里写带明细的文本快照」（那会掏空审计级留痕的举证语义）。结构化行**不过** `mask_pii`：它的字段面是封闭列集合、值就是客户可见视图里的值，对账号再打一次码只会让回看与实时不一致。 |
| Q9 | **标签落点与缺失行为（A）**：进 `ViewSpec` + 集成测试断言；缺标签回落英文列名。漂移在 CI 里炸，而不是在客户面前炸，也不悄悄吞掉一列。 |
| Q10 | **客户载荷独立成形（A）**：`data_answer` 是客户契约，不复用内部 `AnalyticsQueryResponse`（不把 `sql` 带出去）；`views` 用中文 label；`/messages` 信封式端点与 `/stream` 的 `done` 帧共享同一 `ChatResponse`，形状一视同仁。 |
| Q11 | **文本措辞与出现时机（A）**：「为您查到 N 行数据（结果超出行数上限，已截断），已列在下表。数据口径：<视图口径>」；表随 `done` 到达、文本打字机播完后出现，不打字机播表格。 |
| Q12 | **维度裁剪（A）**：后端在出客户契约那一步剔除 `customer_id`；其余列（含 `payee_account` 完整账号）原样给，与客户流水页同口径。裁剪发生在后端，不靠前端隐藏（ADR-0016 同一条纪律）。 |

### 第三轮

| # | 决定 |
|---|---|
| Q13 | **回放模式的预置解读文本对客户失效（A）**：`audience == CUSTOMER` 时不采信 `preset.interpretation`（预置 SQL 照旧使用）；加断言「客户可见的 `answer` 与 `data_answer` 里不出现 `va_`」。这是本次改动顺带暴露的既有泄露，不收口就会留下「客户能读到内部视图名」的实例。 |
| Q14 | **内部端不带这个字段（A）**：`_serialize_message`（客户经理视角）不动。归档举证的唯一对象是客户视角；要看数据，内部端有授权面更宽的视图。 |
| Q15 | **拆四份 issue（A）**：① 后端客户数据契约 → ② 归档与客户历史 → ③ 客户侧渲染 → ④ 收口与文档。顺序推进，**第三份做完即有可演示的完整状态**。 |

## 关键事实基线

实现时可直接引用，不必重新检索。

| 事实 | 依据 |
|---|---|
| `done` 帧 = 整个 `ChatResponse` 的 `model_dump()`；`delta` 帧无事件名；帧构造只有 `_sse_frame` 一个出口 | `backend/app/api/chat.py:81-95` |
| `ChatResponse{answer, citations, intent, content_classification, trace_id, degraded}` 无行列字段 | `backend/app/agent/schemas.py:17-27` |
| 客户侧解析：`event === "done"` 走 `onDone`，**其余一律当 delta**（新事件名会追加 `undefined`） | `apps/customer/src/chat/api.ts:117-121` |
| `data_query_node` 把 `interpretation` 当 answer；`_data_query_material` 只留 `sql/views/row_count/truncated/error_code`，`result.columns`/`rows` 当场丢弃 | `backend/app/agent/graph.py:420-434,138,141-150` |
| 三出口话术常量：失败 `DATA_QUERY_FAILURE_MESSAGE`、零行 `DATA_QUERY_EMPTY_MESSAGE`、白名单外由 `catalog.queryable_topics` 生成 | `backend/app/agent/graph.py:73-89,129-138` |
| 客户侧解读恒走 `_fake_customer_interpret`（`audience == CUSTOMER` 或 fake provider）；它调用 `_row_lines` 与 `_column_counts` | `backend/app/analytics/interpretation.py:71-72,104-148` |
| `_row_lines` / `_column_counts` 同时被员工/模型路径使用（`_row_lines(result, limit=_ROW_PREVIEW_LIMIT)`），**不能删** | `backend/app/analytics/interpretation.py:151-161` |
| 回放分支先于 audience 判断返回 `preset.interpretation`，而 `ANALYTICS_PRESETS[0]` 的目标视图 `va_product_element` 在客户候选集里 | `backend/app/analytics/interpretation.py:66-70`、`backend/app/replay/library.py:228-240`、`backend/app/agent/config.py:24` |
| 客户域四视图列名全英文 snake_case；视图中文名与口径在 `ViewSpec`（`label` / `summary` / `keywords`） | 迁移 `0030`、`backend/app/analytics/catalog.py:69-120` |
| 客户候选集 = 四张 `va_my_*` + `va_product_element`；员工侧视图不在其中 | `backend/app/agent/config.py:21-24` |
| 行数上限 200、超时 5000ms 在同一配置上，截断由 `fetchmany(max_rows+1)` 判定 | `backend/app/settings.py:24,26`、`backend/app/analytics/execution.py:88-105` |
| 归档 assistant 行只写 `content`（脱敏文本）+ `citations` + `tool_calls` + `content_classification`；`mask_pii` 三条正则在 `archive.py:32-34,63-70` | `backend/app/agent/archive.py:98-110` |
| `get_customer_session` 只回 `role/content/citations/created_at`；内部端 `_serialize_message` 另有一套 | `backend/app/agent/archive.py:114-123,317-350` |
| 客户历史字段白名单断言（子集式，多一个字段就红） | `backend/tests/test_customer_conversations.py:127-130` |
| SSE 帧序列断言：`done` 之前的帧必须都是无名事件，`done` 必须是最后一帧；payload 按键取值 | `backend/tests/test_chat_stream.py:103-110` |
| 前端 `api.spec.ts` 对 `onDone` 载荷是**深度相等**；`ChatPage.spec.ts` 直接喂 mock、不看帧形状 | `apps/customer/src/chat/api.spec.ts:74-81`、`ChatPage.spec.ts:10-18` |
| 客户侧三处表格是原生 `<table>` + `data-testid`：`.table-wrap` 横向滚动、缺值统一 `—`、数字列 `tabular-nums` | `apps/customer/src/trading/TransactionHistory.vue:95-130,187-225` |
| 客户侧 EP 是全量注册（`app.use(ElementPlus)`），`el-table` 开箱可用——本 slice 仍不用它 | `apps/customer/src/main.ts:2,13` |
| 迁移 head 是 `0032`，本 slice 的新迁移为 `0033` | `backend/migrations/versions/` |
| 测试需要真实 MySQL/Redis（Milvus 缺失只记日志）；命令：`python -m pytest tests/<file>.py`（在 `backend/` 下）、`pnpm typecheck`、`pnpm test` | `backend/tests/conftest.py:54-148`、根 `package.json:12-13` |
| 演示脚本第七节与断言表会因本 slice 失效 | `docs/demo-script.md:161-181,214-219` |

## Implementation Decisions

遵循 `docs/adr/`。本 slice 直接受 ADR-0028（本次新增）、ADR-0025（复用分析链路与三出口）、ADR-0015
（客户历史复用归档）、ADR-0016（客户侧不共用内部序列化）约束。**员工侧 `AnalyticsQueryResponse`、
`validate_query`、受限账号机制、`el-table` 与内部气泡全部不动。**

### 后端客户数据契约（#01）

- `ChatResponse` 新增可选 `data_answer`，形状：

  ```json
  {
    "columns": [{"key": "product_name", "label": "产品名称"}],
    "rows": [["稳健增利", "120000.00"]],
    "row_count": 1,
    "truncated": false,
    "views": ["持仓明细"]
  }
  ```

  `row_count` 是**已返回**的行数（与内部 `AnalyticsQueryResponse` 同口径），是否被截断由 `truncated` 表达。
- 只有「有行」出口产出它；失败/超时、零行、白名单外一律 `null`，三句话术一字不改。
- `answer_customer_data_question` 的返回结构（`DataQueryTurn`）多带一份结构化结果；`_data_query_material`
  与调试级留痕的字段保持原样（SQL 仍然只进 30 天留痕）。
- 列标签：`ViewSpec` 增 `column_labels`，四张客户视图补齐中文标签；`customer_id` 在出契约时剔除。
- 文本收敛：`_fake_customer_interpret` 去掉 `_row_lines` / `_column_counts` 调用（这两个函数仍被员工与模型
  路径使用），文案为「为您查到 N 行数据（结果超出行数上限，已截断），已列在下表。数据口径：<口径>」。
- 回放模式：`audience == CUSTOMER` 时不采信 `preset.interpretation`，走确定性模板；预置 SQL 照旧使用。
- 两个端点（`/api/customer/chat/messages` 与 `/api/customer/chat/stream` 的 `done` 帧）共享同一 `ChatResponse`，
  **不新增 SSE 事件名**。

### 归档与客户历史（#02）

- 新迁移 `0033` 给 `conversation_archive` 加一列（JSON、可空）存结构化结果；模型同步加字段。
- `record_turn` 增 `answer_data` 形参，只写进 assistant 行；**不过 `mask_pii`**。
- `get_customer_session` 显式把 `data` 带给客户（assistant 消息，无表时为 `null`）；内部端 `_serialize_message`
  不动。
- 更新客户历史字段白名单断言，把 `data` 显式写进去——改断言的动作本身就是“这一步是刻意的”的记录。

### 客户侧渲染（#03）

- `ChatStreamDone` 增可选 `data_answer`；`ChatMessage` 增可选 `dataAnswer`，`finishTurn` 带上（与 `citations`
  同一路径）。
- 新组件 `DataAnswerTable.vue`：原生 `<table>`，表头取 `columns[].label`，行是拉链式二维数组配成对象；
  `.table-wrap` 横向滚动、数字列 `tabular-nums`、缺值 `—`、`data-testid="data-answer-table"`。
- 气泡次序：文本（打字机播完）→ 结果表 → 与表同层的「共 N 行」与截断提示（`data-testid="data-answer-truncation"`）。
- 客户历史回看复用同一组件与同一类型，不另写一份。

### 收口（#04）

- 前端 `api.spec.ts` 的深度相等断言补 `data_answer`；确认 SSE 帧序列断言不破（不新增事件名）。
- 后端回归与护栏：`va_` 不外泄、员工侧视图仍不在客户候选集、三出口 `data_answer` 为空、超 200 行截断。
- `docs/demo-script.md` 第七节与断言表改写；`docs/roadmap.md` 与本 spec / ADR-0028 核对一致。

## Testing Decisions

沿用既有 seam（后端 HTTP 测试 + 前端 vitest），不新增测试 seam。

- 客户问「我持有哪些产品」：`data_answer.columns` 的 `label` 全是中文、无 `customer_id`、`len(rows) ==
  row_count`；`answer` 里不含英文列名、不含 `va_`。
- 零行 / 失败 / 白名单外：`data_answer` 为空，`answer` 与既有话术逐字一致（零行与失败仍可区分）。
- 截断：构造超过 200 行的结果 → `truncated == true`、`len(rows) == 200`、文本含截断提示。
- 归档：一轮数据问答后，客户历史详情的 assistant 消息带 `data`；同一会话里的知识问答那轮为 `null`；内部
  端会话详情不出现该字段。
- 回放：客户问出 `ANALYTICS_PRESETS[0]` 的原句，得到确定性模板文本 + 结果表，文本里不出现 `va_`。
- 前端：表格渲染行列与缺值 `—`、截断提示、历史回看渲染同一张表、无表时不留空壳。
- 收尾：`python -m pytest`、`pnpm typecheck`、`pnpm test` 全绿。

## Out of Scope

- **图表化、CSV 导出、分页、排序、列筛选**：客户侧的场景是「看自己的账」，不是做分析；内部侧的 CSV 导出
  不跟随到客户端。
- **客户看到 SQL**：不给，理由见 ADR-0028。
- **内部端字段改动**：`AnalyticsQueryResponse`、`el-table`、`_serialize_message` 一行不动。
- **表格进上下文**：结果表只是呈现层事实，不进短期记忆、不改变追问的语境（追问仍靠 `answer` 文本与既有
  的 `history`）。
- **第二批视图（已签署文件、其余测评字段）、画像 / 服务记录 / 风控预警**：白名单不变。
- **`CONTEXT.md` 词条**：呈现层的形状不进 glossary。
- **多轮下钻**：沿袭 `data-analysis-agent` 与 `customer-nl2sql` 的既有排除。

## Further Notes

- **`docs/adr/0028` 已落（2026-09-27）**：核心记四件事——为什么推翻「不扩展 SSE 表格帧」、为什么归档也要
  存结构化结果、为什么结构化行不过 `mask_pii`、为什么客户侧看不到 SQL / 视图名 / 英文列名。六条被拒方案
  （新 SSE 事件、新端点、只做实时、文本快照、LLM 中文别名、复用 `el-table`）都在里面。
- **`docs/roadmap.md` 的改动（已落）**：横切 slice 段落补一条本 slice 的说明；收尾清单补一行。
- **两条品味线**：零行与失败必须可区分（一张空表会把它们抹平）；客户可见的文本与结构都不含内部标识
  （`va_`、SQL、英文列名、`customer_id`）——后者由测试钉住，不靠约定。
- **本次改动顺带收口一条既有泄露**：回放模式下客户可能拿到员工口吻、且写出内部视图名的预置解读（Q13）。
  它是 `customer-nl2sql` 的遗留，不是本 slice 引入的，但由本 slice 的文本收敛放大。
- **契约变更的成本记在 ADR-0028 的 Consequences 里**：客户侧 SSE 契约第一次长出结构，以后再加字段时该
  知道前端有深度相等断言在盯着。
