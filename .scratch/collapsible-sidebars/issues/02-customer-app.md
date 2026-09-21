# 02 — customer 接线：左栏折叠 + 持久化

**What to build:** 在 customer 应用接上 01 的受控折叠：新增 `layout` store（`sidebarCollapsed` + localStorage 持久化），`CustomerShell` 把折叠状态经 `v-model:sidebar-collapsed` 交给 `AppShell`。customer 只有两栏、没有检查器，本 issue 只涉及左栏折叠。

**Blocked by:** 01 — shared 壳受控折叠

**Status:** ready-for-agent

- [ ] 新增 `apps/customer/src/stores/layout.ts`：`sidebarCollapsed`，初始从 localStorage 读、缺省 `false`，toggle 写回；key 沿用 customer 既有 localStorage 前缀
- [ ] `CustomerShell.vue`：`v-model:sidebar-collapsed` 接 `AppShell`；customer 不传 `inspectorCollapsed`（无检查器）
- [ ] 折叠状态是浏览器级偏好，登录/登出**不**清空
- [ ] 测试：store 读写 localStorage、刷新恢复、缺省展开；`CustomerShell` 挂载后折叠状态与 `AppShell` 同步
- [ ] `pnpm --filter @wealth/customer typecheck` 与 `test` 全绿

## 落地要点

- customer 主区是 `--wm-content-max-width` 限宽居中，左栏折叠只是主区可用宽度变大，居中逻辑不动。
- 不要在这个 issue 里顺手加「检查器」或改页面内容——那属于 internal。
