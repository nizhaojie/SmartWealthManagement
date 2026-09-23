# 01 — 会话标识改由登录凭证承载

**What to build:** 数据分析的会话不再由前端页面生成。后端在请求体没有 `session_id` 时取登录凭证里的 `sid`，于是同一次登录里的追问共用一个上下文，刷新与切模块都不打断；重新登录即新会话由 Redis 白名单保证，而不是靠前端自觉。这是本 slice **唯一**的后端改动。

**Blocked by:** 无

**Status:** ready-for-agent

- [ ] `backend/app/api/analytics.py` 的 `run_analytics_query` 改为 `session_id=body.session_id or auth.session_id`
- [ ] `body.session_id` 显式传值时**仍然覆盖**凭证——这是「清空对话」的机制前提，必须有断言
- [ ] `AnalyticsQueryRequest.session_id` 保持可选，注释更新为「缺省时取登录会话」
- [ ] **风控问答路由不动**：`backend/app/api/risk_query.py` 继续传 `body.session_id`，行为零变化
- [ ] 前端 `apps/internal/src/analytics/api.ts` 不再无条件带 `session_id`；`types.ts` 的 `AnalyticsQueryInput.sessionId` 改为可选并写明唯一用途（清空后覆盖）
- [ ] 断言：同一次登录的两次提问落在同一个记忆键上，「那上个季度呢」进得了上下文
- [ ] 断言：缺省时不因少了 `session_id` 报错
- [ ] 断言：风控问答的 `session_id` 语义未变（它的两次页面级提问仍互不共享）

**实现落点：** `backend/app/api/analytics.py`、`backend/app/analytics/service.py`（`_memory_session` 不动）、`apps/internal/src/analytics/api.ts`、`types.ts`；测试沿用 `backend/tests/test_analytics_query.py` 与 `test_short_term_memory.py` 的手法。

**验收：** 同一次登录里问两句，第二句「那上个季度呢」被正确理解；重新登录后同一句话不再带上一次的上下文。既有护栏测试 3 全数保持通过。
