# 01 — shared 壳受控折叠

**What to build:** 在 `packages/shared` 的 `AppShell` 上加受控折叠能力：新增 `sidebarCollapsed` / `inspectorCollapsed` 两个受控 prop 与 `update:sidebarCollapsed` emit（`v-model:sidebar-collapsed`）；侧栏底部加一条触发条；折叠态下品牌显示首字符、导航 label 隐藏、badge 变图标角标、hover 出 tooltip；新增令牌 `--wm-sidebar-width-collapsed: 64px` 并让左栏折叠、检查器折叠两个 grid 形态落地。不触碰任何应用页面——两端都消费这一刀，它没固化之前不要动 customer / internal。

**Blocked by:** 无

**Status:** ready-for-agent

- [ ] 令牌：`--wm-sidebar-width-collapsed: 64px` 加入 `tokens.css`，`tokens.ts` 只读镜像同步（若该值被 TS 侧引用）
- [ ] `AppShell` 新增 props `{ sidebarCollapsed?, inspectorCollapsed? }`、emit `{ 'update:sidebarCollapsed' }`；`sidebarCollapsed` 走 `v-model:sidebar-collapsed`
- [ ] 左栏折叠：`app-shell--sidebar-collapsed` class，grid 第一列从 `--wm-sidebar-width` 换成 `--wm-sidebar-width-collapsed`
- [ ] 检查器折叠：`app-shell--inspector-collapsed` class，grid 回到两列（与 `<1200px` 同形态、由状态驱动）；折叠时不渲染第三栏列，即使 `inspector` 插槽存在
- [ ] 触发条：侧栏最底部（`sidebar-footer` 下方）一条占满宽度细按钮，双箭头图标，`aria-label` + `aria-expanded`；点击 emit `update:sidebarCollapsed`
- [ ] 折叠态渲染：品牌显示首字符方块（subtitle 隐藏）；nav label 隐藏、hover 图标出 `el-tooltip`；nav `badge` 变图标右上角小圆点
- [ ] `sidebar-footer` 槽在折叠态仍渲染、内容不裁剪（折叠长什么样子由内容方决定）
- [ ] 折叠/展开宽度过渡，包在 `prefers-reduced-motion: no-preference` 内
- [ ] `AppShell.test.ts` 更新：折叠 class、触发条 emit、label 隐藏、badge 变角标、`inspectorCollapsed` 第三栏不占列、`aria-expanded`
- [ ] `pnpm --filter @wealth/shared test` 与 `pnpm typecheck` 全绿；`check-boundary.mjs` 不命中

## 落地要点

- 受控，状态不留 shared：`AppShell` 只认两个布尔 + 触发条，不读 localStorage、不建 store。
- 检查器折叠没有壳内触发（开关在 internal 顶栏），所以 `inspectorCollapsed` 是纯 prop、不 emit。
- 触发条与「折叠」是纯 UI，可进 shared；「检查器」「预警」这类词一个都不能出现（`check-boundary.mjs` 词表会拦）。
- 别顺手把 `<1200px` 的媒体查询规则删掉——它保留，折叠只是叠加在它之上。
