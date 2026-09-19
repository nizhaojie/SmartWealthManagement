# 03 — 顾问侧回看已放行内容

**What to build:** 「我审核过的记录」这张表补上入口。后端能力与页面都已经在：`AdvisoryReviewPage` 在状态为已放行时会自动加载并渲染 AI 原稿与顾问定稿并排，`getFinal` 也早已封装。缺的只是历史表忘了接同一根线——「待审核」表有「查看」按钮走 `openReview(row.draft_id)`，历史表没有。

顺带把这页的两种场景分开：`decided` 为真时它不再是「审核」，而是「查看」。

**Blocked by:** 无（不依赖 01，可与 01 / 02 并行）

**Status:** ready-for-agent

- [ ] `AdvisoryWorkspace.vue` 的「我审核过的记录」表加「查看」列，复用已存在的 `openReview(row.draft_id)`，路由仍是 `advisory-review`
- [ ] 放行记录与驳回记录都能回看（两者都有 `draft_id`）
- [ ] `AdvisoryReviewPage` 在 `decided`（已放行 / 已驳回）状态下：`PageHeader` 标题由「审核」改为「查看方案」，面包屑同步
- [ ] 同状态下「返回队列」按钮文案改为「返回投顾助手」（它回到的是工作台，不是审核队列）
- [ ] 不在已决定状态下新增任何放行 / 驳回入口（`v-if="isAdvisor && !decided"` 已挡住，别改动它）
- [ ] **组件测试：历史表每行可点进 `advisory-review` 路由**
- [ ] **组件测试：已放行状态下标题为「查看方案」，且不存在放行 / 驳回入口**
- [ ] 组件测试：放行前的待审状态仍显示「审核」标题与审核决定面板，不被本次改动影响
