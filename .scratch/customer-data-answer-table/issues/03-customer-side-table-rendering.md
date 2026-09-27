# 03 — 客户侧渲染：对话气泡与历史回看里的结果表

**What to build:** 客户侧对话在文本播完后渲染结果表（原生 `<table>` + 既有令牌与 `data-testid` 约定），带
「共 N 行」与截断提示；历史回看复用同一个组件。**本份做完即有可演示的完整状态。**

**Blocked by:** `02-archive-and-customer-history`（历史回看要用到 `data` 字段）。

**Status:** implemented

- [x] `ChatStreamDone`（`apps/customer/src/chat/api.ts`）增可选 `data_answer`，与后端形状逐字段对齐
- [x] `ChatMessage`（`apps/customer/src/stores/chat.ts:9-15`）增可选 `dataAnswer`；`finishTurn`（`:59-67`）与
      `citations` 同一路径带上它
- [x] 新组件 `apps/customer/src/chat/DataAnswerTable.vue`：原生 `<table>`，表头取 `columns[].label`，二维 `rows`
      拉链成对象；`.table-wrap` 横向滚动、数字列 `tabular-nums`、缺值统一 `—`、
      `data-testid="data-answer-table"`（做法对齐 `apps/customer/src/trading/TransactionHistory.vue:95-130,187-225`）
- [x] 气泡次序（`ChatPage.vue:132-156`）：文本（打字机播完）→ 结果表 → 同层的「共 N 行」与截断提示
      （`data-testid="data-answer-truncation"`）；**无表时不渲染空壳**
- [x] 历史回看（`apps/customer/src/chat/ChatHistoryDrawer.vue:158-205`）复用同一组件与同一类型；
      `history.ts` 的消息类型加 `data`
- [x] 断言（vitest）：表格渲染行列与中文表头、缺值 `—`、截断提示出现/不出现、无表时不出现表格容器
- [x] 断言（vitest）：`ChatPage.spec.ts` 的 `onDone` 载荷带结构化结果时渲染出表；不带时与今日一致
- [x] 断言（vitest）：`ChatHistoryDrawer.spec.ts` 的历史详情渲染出表

**实现落点：** `apps/customer/src/chat/`（新组件 + `ChatPage.vue` + `ChatHistoryDrawer.vue` + `api.ts` +
`history.ts`）、`apps/customer/src/stores/chat.ts`。

**验收：** 客户问「我持有哪些产品」→ 先出文本、再出带中文表头的表格与行数；问一句白名单外的问题 → 只有文本、
没有空表；打开历史记录 → 同一条回答里也有那张表。`pnpm typecheck` 与 `pnpm --filter @wealth/customer test`
通过。
