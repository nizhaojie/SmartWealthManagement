# 左右栏折叠/展开

Status: ready-for-agent

前置：`frontend-rebuild`（`AppShell` 双形态骨架、`sidebar-footer` 槽、导航 badge、各端 Pinia 装配）

本 slice **不修改**后端，也不新增 ADR、不改 `CONTEXT.md`（判定见 Further Notes）。

## Problem Statement

两端外壳的栏宽是死的。`packages/shared/src/shell/AppShell.vue` 用 CSS Grid 撑起骨架：左导航取 `--wm-sidebar-width: 248px`、右检查器取 `--wm-inspector-width: 336px`（`packages/shared/src/theme/tokens.css`），只有两条响应式规则——`<1280px` 收窄到 220/300，`<1200px` 第三栏 `display:none`（`AppShell.vue` 的 `@media (max-width: 1199px)`）。除此之外没有任何收起手段。

internal 是三栏（左导航 + 主区 + 右检查器，检查器仅当页面注入 `inspector` 插槽时出现），customer 恒两栏（左导航 + 主区限宽居中）。当用户在专注主区、或屏幕偏窄时，两翼的固定宽度是纯浪费：336px 的检查器在不需要看客户上下文时占掉近四分之一屏宽，用户却没有任何办法让它让位。

这是中后台外壳最基础的能力缺口——「侧栏可收起」。本 slice 补齐：两端左导航可折叠成图标条，internal 右检查器可完全隐藏。

## Solution

给两端左导航加「折叠成图标条」、给 internal 右检查器加「完全隐藏」；折叠状态**全局**、按端用 localStorage 持久化、默认展开。机制收在 shared 的 `AppShell`（受控折叠 + 触发条），状态归各端 Pinia `layout` store。

## 访谈结论清单（grill-with-docs，2026-09-21）

### 第一轮

| # | 决定 |
|---|---|
| Q1 | 语义 = **折叠/展开**（collapse），不是拖拽调整宽度、不是预设档位。拖拽分支（min/max 宽度、拖拽手柄、双击重置）整条砍掉。 |
| Q2 | 范围 = **两端左栏（customer + internal）+ internal 右检查器**。 |
| Q3 | 持久化 = **localStorage，按端区分 key**（沿用 ADR-0004 身份域隔离的既成事实：两端 localStorage key 本就不同）。 |

### 第二轮

| # | 决定 |
|---|---|
| Q4 | 左栏折叠形态 = **图标条（icon rail，64px）**，品牌显示首字符方块、subtitle 隐藏、导航文字隐藏、hover 出 tooltip；internal 的 `sidebar-footer` 小卡折叠时**做「图标+角标」**，不是隐藏。 |
| Q5 | 右检查器折叠形态 = **完全隐藏 + 顶栏右侧开关按钮**（`WorkbenchShell` 注入，不进 shared）。 |
| Q6 | **默认展开**；折叠作用域**全局**（跨页面）。 |
| Q7 | `<1200px` 第三栏自动隐藏**保留不动**（手动折叠是持久化状态、窄屏自动隐藏是兜底，两者正交）。 |

### 第三轮

| # | 决定 |
|---|---|
| Q8 | 左栏折叠触发按钮 = **侧栏最底部**（`sidebar-footer` 下方一条占满宽度的细触发条，双箭头），放 shared。 |
| Q9 | 交付物 = spec + 三份 issue（shared → customer → internal）+ 更新 roadmap；**`CONTEXT.md` 零改动、不新增 ADR**。 |

## User Stories

### 客户

1. As a 客户, I want to 把左侧导航收起成一条图标, so that 对话与资产内容获得更宽的视野
2. As a 客户, I want to 刷新或重新登录后侧栏还是我之前收起的那个状态, so that 我不必每次都重新收一遍

### 内部员工

3. As a 理财顾问, I want to 在审核方案时把右侧检查器收起, so that AI 原稿与定稿获得全部屏宽
4. As a 风控专员, I want to 处置预警时把检查器展开、处置完收起, so that 主区表格不被 336px 的检查器挤窄
5. As a 内部员工, I want to 左侧导航收起后仍能看到「今日风险预警」的待办数（一个图标+角标）, so that 我不用为了这个数字展开侧栏
6. As a 内部员工, I want to 折叠状态在切换页面后保持不变, so that 它不会在 A 页收起、跳到 B 页又弹出来

### 开发者

7. As a 开发者, I want to 折叠机制收在 shared 的 `AppShell` 且只认识「折叠」这个 UI 概念, so that 两端不各写一份、也不把「检查器」「预警」这类业务词带进 shared
8. As a 开发者, I want to 折叠状态由各端 store 持有并按端持久化, so that customer 与 internal 互不串值

## Implementation Decisions

### 令牌与折叠形态

- 新增令牌 `--wm-sidebar-width-collapsed: 64px`（EP `el-menu` 惯例）。`--wm-sidebar-width` / `--wm-inspector-width` 保持不变。
- 左栏折叠：`AppShell` 挂 `app-shell--sidebar-collapsed`，grid 第一列从 `--wm-sidebar-width` 换成 `--wm-sidebar-width-collapsed`。
- 右检查器折叠：`AppShell` 挂 `app-shell--inspector-collapsed`，grid 回到两列（与 `<1200px` 的塌陷同形态，但由状态而非媒体查询驱动）。
- 折叠/展开带宽度过渡，包裹在 `prefers-reduced-motion: no-preference` 内（沿用既有动效纪律）。

### AppShell 受控折叠（shared）

`AppShell` 新增受控 props 与 emit，状态不留在 shared：

- props：`sidebarCollapsed?: boolean`、`inspectorCollapsed?: boolean`。
- emit：`update:sidebarCollapsed`（`v-model:sidebar-collapsed`）——触发条在壳内，点击即 emit。
- `inspectorCollapsed` 是纯受控 prop，无壳内触发（开关在 `WorkbenchShell` 顶栏，见下）。

折叠态下的壳内渲染：

- **品牌**：纯文字插槽（无 logo 资源），折叠时显示首字符方块（「内」「智」），subtitle 隐藏。
- **导航项**：label 隐藏，hover 图标出 `el-tooltip` 显示 label；`badge` 从「文字旁数字」变成「图标右上角小圆点」。
- **`sidebar-footer`**：槽继续渲染、内容不裁剪——折叠态长什么样由内容方自己决定（internal 的 `RiskAlertSummaryCard` 读 store 判断），壳不管。
- **触发条**：侧栏最底部一条占满宽度的细按钮（双箭头图标），`aria-label` 与 `aria-expanded` 齐全。

### 各端 layout store + 持久化

每端新增一个 `layout` store（Pinia），字段与 localStorage：

- customer：`sidebarCollapsed`；internal：`sidebarCollapsed` + `inspectorCollapsed`。
- 初始值从 localStorage 读、缺省 `false`；toggle 时写回。key 各端独立（沿用两端既有 localStorage 前缀），登录/登出**不**清空——它是浏览器级偏好，不随身份走。

### internal 检查器开关

- `WorkbenchShell` 顶栏右侧加一个「检查器」开关按钮，**仅当 `pageSlots.inspector.value` 非空时显示**；点击 toggle `layout.inspectorCollapsed`。
- 折叠后 `AppShell` 因 `inspectorCollapsed` prop 不再渲染第三栏列，即使 `inspector` 插槽仍被注入。页面侧 `useInspector()` 逻辑不动。

### sidebar-footer 折叠态（internal）

`RiskAlertSummaryCard` 折叠时渲染**图标 + 角标**：

- 图标（预警/铃铛），角标 = 待处理数；`N=0` 不显示角标、失败态仅图标（与现状的空态/失败语义对齐，只是折叠下不显示文字）。
- 点击仍跳 `/risk-monitoring`，数据来源不变（`listAlerts({status:"未处理"})`）。

## Testing Decisions

### Seam — Vue 组件挂载 + store 单测

- **shared `AppShell.test.ts`**：`sidebarCollapsed` 挂 class、grid 第一列走 collapsed 令牌；触发条点击 emit `update:sidebarCollapsed`；折叠时 nav label 不渲染、badge 变角标、品牌显示首字符；`inspectorCollapsed=true` 时第三栏不占列（即使有 `inspector` 插槽）；`aria-expanded` 反映状态。
- **customer**：`layout` store 读写 localStorage；刷新恢复上次状态；缺省展开。
- **internal**：检查器开关仅在有 inspector 的页面出现；折叠后第三栏消失、再展开恢复；`sidebar-footer` 折叠态渲染图标+角标（N=0 不显示角标、失败仅图标）；`inspectorCollapsed` 与 `sidebarCollapsed` 各自独立持久化。
- 既有 `AppShell.test.ts` 两栏/三栏形态断言、`RiskAlertSummaryCard` 断言重跑不破。

## Out of Scope

- **拖拽调整宽度**（min/max 宽度、拖拽手柄、双击重置、预设档位）——Q1 明确砍掉。
- **移动端 / 完整响应式适配**——只保留既有 `<1280px` / `<1200px` 两条规则。
- **后端任何改动**——含「布局偏好」的跨设备同步（localStorage 只是浏览器级）。
- **折叠态逐页独立**——作用域定为全局（Q6）。
- **EP 组件内部着色的无障碍加固**（沿袭 `frontend-rebuild` 的排除）。

## Further Notes

- **`CONTEXT.md` 零改动**：「折叠/展开」「图标条」「触发条」都是 UI 交互词汇，不是领域术语。glossary 只收领域概念，故不新增词条。
- **不新增 ADR**：三项门槛（hard to reverse / surprising without context / real trade-off）都不满足——折叠可逆、是既有惯例、localStorage 持久化无真实取舍。与 `frontend-rebuild` 记录「不新增 ADR」同一条理由。
- **shared 边界（ADR-0003）**：`AppShell` 只新增「折叠」这个纯 UI 概念（`sidebarCollapsed` / `inspectorCollapsed` 两个布尔 + 触发条）。「检查器」开关由 `WorkbenchShell` 注入顶栏、不进 shared；`AppShell` 对「检查器」一无所知，只认 `inspectorCollapsed` 布尔。`check-boundary.mjs` 词表不命中。
- **与 `<1200px` 规则正交**：手动折叠是持久化的用户主动状态，窄屏自动隐藏是瞬时的兜底，两者叠加不冲突——窄屏下第三栏无论手动状态如何都应让位给主区。
