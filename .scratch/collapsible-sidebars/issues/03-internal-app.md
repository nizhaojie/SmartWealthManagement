# 03 — internal 接线：左栏折叠 + 检查器开关 + footer 折叠态

**What to build:** 在 internal 应用接上 01 的受控折叠：新增 `layout` store（`sidebarCollapsed` + `inspectorCollapsed` + localStorage），`WorkbenchShell` 接左栏折叠、加顶栏「检查器」开关、并让 `sidebar-footer` 的 `RiskAlertSummaryCard` 在折叠态渲染图标+角标。

**Blocked by:** 01 — shared 壳受控折叠

**Status:** ready-for-agent

- [ ] 新增 `apps/internal/src/stores/layout.ts`：`sidebarCollapsed` + `inspectorCollapsed`，各自从 localStorage 读、缺省 `false`、toggle 写回；key 沿用 internal 既有前缀
- [ ] `WorkbenchShell.vue`：`v-model:sidebar-collapsed` + `:inspector-collapsed` 接 `AppShell`
- [ ] 顶栏右侧加「检查器」开关按钮，**仅当 `pageSlots.inspector.value` 非空时显示**，点击 toggle `layout.inspectorCollapsed`
- [ ] `RiskAlertSummaryCard.vue` 读 `layout.sidebarCollapsed`：折叠态渲染图标 + 角标；N=0 不显示角标、失败态仅图标；点击仍跳 `/risk-monitoring`，数据来源不变
- [ ] 测试：检查器开关仅在有 inspector 的页面出现；折叠后第三栏消失、再展开恢复；footer 折叠态图标+角标（0 不显示、失败仅图标）；两个布尔各自独立持久化
- [ ] `pnpm --filter @wealth/internal typecheck` 与 `test` 全绿

## 落地要点

- 检查器开关放 `WorkbenchShell`（顶栏右侧已有 `topbarActions` 注入位旁），**不进 shared**——shared 不认「检查器」这个词，只认 `inspectorCollapsed` 布尔。
- 页面侧 `useInspector()` 逻辑不动：折叠是壳布局偏好，与「页面是否注入检查器」是两回事。
- `RiskAlertSummaryCard` 的图标与角标颜色出自既有令牌（`--wm-color-danger`），不要引入新色值。
- 折叠状态是浏览器级偏好，登录/登出不清空。
