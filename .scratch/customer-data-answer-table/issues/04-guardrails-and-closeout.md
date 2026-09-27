# 04 — 收口：契约断言、护栏与演示脚本

**What to build:** 把这次契约变更的既有断言全部对齐（前端深度相等、SSE 帧序列、客户历史白名单），补齐护栏断言，
改写演示脚本，并核对 roadmap / spec / ADR 三份文档一致。

**Blocked by:** `03-customer-side-table-rendering`。

**Status:** implemented

- [x] 前端 `apps/customer/src/chat/api.spec.ts:74-81` 的**深度相等**断言补上 `data_answer`（这是客户侧 SSE 契约
      第一次长结构，断言要写得能挡住下一次静默加字段）——`onDone` 载荷换成一份完整的 `data_answer`，
      `toHaveBeenCalledWith` 逐字段比对整份嵌套结构
- [x] 确认 SSE 帧序列断言不破：`backend/tests/test_chat_stream.py:103-110`（`done` 之前不得出现具名事件、
      `done` 必须是最后一帧）——本 slice 不新增事件名
- [x] 护栏断言：客户可见的 `answer` 与 `data_answer` 里不出现 `va_` 前缀、不出现 SQL、不出现英文列名
      （`test_the_customer_visible_surface_carries_no_internal_identifiers`）。写这条时发现**口径说明原本会
      原样带出英文列名**（`market_value 是当前市值`）——那是客户可见文本，本次把客户域四张视图的 `summary`
      改成中文标签说法，并把 `va_my_risk_assessment` 的「风险等级」标签纠正为 CONTEXT.md 的「风险承受等级」
- [x] 护栏断言：员工侧视图仍不在客户候选集（`backend/app/agent/config.py:24` 的候选集不含 `va_risk_alert_stat`
      等）；行级范围仍锁死凭证客户，注入身份也改不了范围
- [x] 回归断言：零行 / 失败 / 白名单外三种出口 `data_answer` 为空且话术与今日逐字一致
      （新增 `test_the_three_exits_keep_todays_wording_verbatim`：既有用例断的是常量本身，常量被改照样绿，
      这一条把屏上那三句抄成字面量）
- [x] `docs/demo-script.md` 第七节改写：台词从「回答是一段文本，数字直接写在里面」改为「文本给口径与行数、
      结果表给逐行数据」，并说明表不出现在零行/失败/越界三种出口；顺带记一句「历史回看里有同一张表」
- [x] `docs/demo-script.md` 断言表（`:214-219`）补本 slice 的测试文件与用例名
- [x] `docs/roadmap.md` 的横切 slice 段落与收尾清单一行与本 spec / ADR-0028 核对一致（已由 #01 落库，逐字核对无出入）
- [x] 收尾：`python -m pytest`（需 `docker compose up -d` 起 MySQL/Redis）、`pnpm typecheck`、`pnpm test` 全绿

**实现落点：** `apps/customer/src/chat/api.spec.ts`、`backend/tests/`（客户数据查询与对话归档两组）、
`backend/app/analytics/catalog.py`（客户可见口径与标签）、`docs/demo-script.md`、`docs/roadmap.md`。

**验收：** 三套测试全绿；按改后的演示脚本走一遍第五幕，台词的每一句都对得上屏幕上的东西。
