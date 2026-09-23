# 05 — 历史查询搬进抽屉，右栏塌陷为两栏

**What to build:** 「历史查询」从右栏第三栏搬进顶栏按钮打开的抽屉，右栏因此空掉、`AppShell` 自动塌陷为两栏。抽屉只有一个态——列表项自带状态 / 行数与错误码，SQL 行内折叠展开；「再问一次」把问题送回输入框。

**Blocked by:** 03 — 对话壳与输入区（同一次页面重构，避免两处反复改同一个文件）

**Status:** ready-for-agent

- [ ] 删除 `DataAnalysisWorkspace.vue` 里的 `useInspector()` 调用与右栏模板；第三栏由 `AppShell` 自动塌陷，**不传 variant**
- [ ] 入口改挂 `AppShell` 的 `topbar-right` 插槽：「历史查询」按钮（页头另有 02 号交付的「清空对话」）
- [ ] 抽屉**一个态**：列表项显示问题、状态、时间、返回行数、截断标记、错误码
- [ ] SQL 在行内折叠展开
- [ ] 「再问一次」把问题送回输入框（**不自动发送**）并关闭抽屉
- [ ] 抽屉脚注写明「留痕不存结果集」——这句话从 `AnalyticsHistoryDetail.vue` 搬过来
- [ ] 分页沿用 `PaginationBar` + `usePagination`（ADR-0024），每次打开抽屉从第一页重取（与客服历史抽屉同口径）
- [ ] `AnalyticsHistoryDetail.vue` 随之折叠掉
- [ ] **改写** `analyticsHistoryRail.spec.ts`：它的前提（文件头「证明这张卡真的在第三栏」）已不存在，改为抽屉的测试，不是打补丁
- [ ] 断言：列记录、SQL 行内展开、「再问一次」把问题送进输入框且抽屉关闭、分页走服务端下一页
- [ ] 断言：挂 `App.vue` 证明数据分析页**不再渲染第三栏**

**实现落点：** `apps/internal/src/analytics/DataAnalysisWorkspace.vue`、`AnalyticsHistoryPanel.vue`、`AnalyticsHistoryDetail.vue`（移除）、`analyticsHistoryRail.spec.ts`（改写）；`AppShell` 的 `topbar-right` 插槽。

**验收：** 打开数据分析页是两栏（无右栏）；顶栏「历史查询」打开抽屉，看到自己的提问记录与状态，展开能看 SQL，点「再问一次」问题回到输入框。
