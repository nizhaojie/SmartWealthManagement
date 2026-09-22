# 03 — 风控列表分页（预警 / 风险关注 / 风控规则）

**What to build:** 风控三个列表各自数字分页，并把预警列表的排序从**前端**下推到后端——这是「排序下推」最典型的一处（现有 `AlertsTab` 是对全量结果前端 `sortAlerts`，分页后必须改后端排序，否则翻页即乱）。

**Blocked by:** 02 — 统一分页机制 + 交易流水端到端

**Status:** ready-for-agent

- [ ] `risk-alerts`、`risk-focus`、`risk-rules` 三个接口接收 `page`/`page_size`，返回 `{items, total, page, page_size}`
- [ ] 预警列表排序下推后端（按等级/状态/时间），前端移除整表 `sortAlerts`；后端补稳定排序键
- [ ] `risk-focus`、`risk-rules` 补稳定排序键（时间倒序 + 行标识兜底）
- [ ] `AlertsTab`、`RiskFocusTab`、`RiskRulesTab` 接 `PaginationBar`，翻页与筛选/排序联动、筛选条件翻页保留
- [ ] 断言：排序字段在服务端生效、翻页不乱序、`total` 为过滤后总数

**实现落点：** `backend/app/api/risk_alerts.py`、`risk_focus.py`、`risk_rules.py` 与对应 service，`apps/internal/src/risk/`（`AlertsTab.vue`、`RiskFocusTab.vue`、`RiskRulesTab.vue`），后端 HTTP 测试与前端 spec。

**验收：** 预警列表按等级排序时，翻页仍整体有序；三个列表总数正确、不重不漏。
