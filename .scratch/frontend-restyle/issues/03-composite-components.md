# 03 — 复合组件：StatCard、SectionCard 与 ChartFrame 令牌化

**What to build:** `packages/shared` 新增两个复合组件并改造一个既有组件：`StatCard`（KPI 卡：标题/数值/环比趋势/图标，彩色左边条）、`SectionCard`（白卡容器：标题栏 + 操作区插槽 + 内容插槽）、`ChartFrame` 的硬编码色值全部换成令牌。这是本 slice 全部的新增共享封装——恰好三个，不再多。

**Blocked by:** 01 — 设计令牌层

**Status:** done

- [x] `StatCard`：props = 标题、数值、趋势（方向 up/down + 文案，着色走红涨绿跌令牌）、accent 枚举、图标插槽
- [x] `StatCard` 左边条 3px，accent 只能取 `{primary, up, down, success, warning, danger}` 枚举——类型层面禁裸色值
- [x] `SectionCard`：标题栏（标题 + 操作区插槽）+ 默认内容插槽，白面、边框、圆角、阴影全部走令牌
- [x] `ChartFrame` 令牌化：`#e6e8eb`/`#1f2937`/`#6b7280`/`#d5d9e0`/`#fafbfc`/`#9aa2ae` 等硬编码值全部替换为令牌引用，渲染行为不变
- [x] 三个组件各有 vitest 挂载测试：props/插槽渲染、accent 枚举约束、ChartFrame 空态/加载态不回归
- [x] shared 与两端既有测试全绿

## 落地要点

- 趋势着色的判定在组件内完成：调用方只传方向与文案，不传颜色——涨跌色语义因此只有一个实现点。
- `SectionCard` 是 04 逐页改造的主要承载物：页面主体的每一块内容都包进它，标题栏操作区容纳现有的按钮/筛选器。
- `ChartFrame` 改造是纯替换：它的空态/加载态/尺寸自适应行为有既有调用方（客户资产页、画像页等），不许借令牌化之机改行为。

## 已知取舍

- `StatCard` 当前在两端真实页面里都没有现成使用方（参考图的 KPI 区属静态落地页之外的形态）——先做进 shared 是因为 04 与后续 slice（如画像、报表类页面）必然需要它，且 accent 枚举现在不定，各页面会先自己发明一套。若 04 完成时仍无真实使用方，保留但不在落地页摆放假数据 KPI。
