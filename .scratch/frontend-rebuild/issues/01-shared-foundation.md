# 01 — shared 地基：02 令牌层、双形态骨架、复合组件与 Pinia 装配

**What to build:** 把 `packages/shared` 从上一轮的浅色骨架升级为 02（企业浅色）的视觉与结构地基：令牌层按 spec「设计令牌层」整节重写；`AppShell` 重做成两形态（有 `inspector` 插槽即三栏，无则两栏）；`SectionCard` 重做成 `PanelCard`、`StatCard` 重做、新增 `MeterBar` 与 `PageHeader`；两个应用装上 Pinia 并各自建 store；`http.ts` / `tokenStore.ts` / `chart/*` 原样保留。每一步的验收都落在「shared 自身可测」，不依赖任何应用页面。

这是本 slice 的第一刀，也是唯一被两端消费的一刀。它没固化之前不要动任何一个应用页面——否则 02 的视觉语言会在第二个应用里漂移成第二种风格。

**Blocked by:** 无

**Status:** implemented

- [x] 令牌层重写：色彩/文字/中性面/圆角/阴影/间距/字体/布局常量全部按 spec 表格落地，含新增的 `--wm-color-primary-strong`、`--wm-content-max-width`、`--wm-inspector-width`、`--wm-font-mono`
- [x] `--wm-color-primary` 取 `#1570F0`（4.56:1）；`--el-color-primary` 及 light-1..9 / dark-2 派生仍用 `color-mix` 现场派生
- [x] 圆角改 6/8/10，卡片阴影与浮层阴影换成 02 的两条值，间距刻度维持 4/8/12/16/24/32
- [x] 去掉 `body::before` 的 grain 噪点层与卡片 hover 上浮；保留 focus-visible 轮廓、自定义滚动条、`::selection`、面板顶部发丝渐变线
- [x] 载入浮现与预警脉冲保留在 `prefers-reduced-motion: no-preference` 内；逐项 `nth-child` 错峰延迟全部删除
- [x] `tokens.ts` 只读镜像同步新值；`tokens.test.ts` 断言文本类与涨跌令牌对白底 ≥ 4.5:1，`--wm-text-placeholder` 以注释声明豁免并限定「仅占位与装饰」
- [x] `AppShell` 重做：props `{ navItems, activeKey, brandSubtitle }`，slots `{ brand, topbar-left, topbar-right, default, inspector, sidebar-footer }`，emits `{ select, logout }`；**三栏由 `inspector` 插槽是否存在自动决定，不传 variant**
- [x] 壳的布局常量全部出自令牌（侧栏 248px、顶栏 60px、检查器 336px）；`navItems[].badge` 渲染为 02 的导航徽标（`--wm-color-danger` 淡底），壳不认识 badge 的业务含义
- [x] **登出入口在壳层恒在**：任何角色、任何路由可见可用
- [x] `SectionCard` → `PanelCard`：卡内标题 + 操作区插槽，视觉对齐 02 的白面 + 发丝线 + 圆角 + 卡片阴影；全仓引用同步更名
- [x] `StatCard` 重做对齐 02 的 KPI 排版层级（标题小字 + 大号数字 + tabular-nums + 左侧色条），accent 仍限枚举 `{primary, up, down, success, warning, danger}`
- [x] 新增 `MeterBar`（02 的 `.meter` / `.track`：标签 + 百分比 + 5px 圆角条），不接业务字段
- [x] 新增 `PageHeader`（面包屑 + 页面标题 + 右侧操作区插槽）
- [x] `ChartFrame` 容器样式并入 02 卡片语言；`chart/palette.ts`、`chart/options.ts` 与 `ChartFrame` 的行为**不动**
- [x] `http.ts` / `tokenStore.ts` 原样保留（`createHttpClient` 的 `onUnauthorized` 与 `postForm` 是既有能力，不要重造）
- [x] 两个应用装上 `pinia`（本 slice 唯一新增运行时依赖）并在 `main.ts` 注册；`@element-plus/icons-vue` 已在依赖里，沿用
- [x] customer 建 `auth` / `chat` store；internal 建 `auth` / `currentCustomer` store；store 内部沿用既有 token/localStorage 语义与 key
- [x] `check-boundary.mjs` 与新组件全部相容（`MeterBar` / `PageHeader` / `PanelCard` / `StatCard` 的名称与内容不命中业务词表）
- [x] `pnpm --filter @wealth/shared test` 与 `pnpm typecheck` 全绿

## 落地要点

- **两步走**：先令牌后组件。令牌表是唯一数值来源，组件里出现裸色值就是这一步没做完。
- `AppShell` 的形态判定只能有一个来源。若未来真需要强制三栏（哪怕 `inspector` 为空），再加 prop；现在不加。
- `MeterBar` 的百分比、标签、颜色全部经 props 传入；不要在 shared 里认识「匹配度」「适当性」这类词。
- 对比度校验复用 `chart/color.ts` 里现成的 `contrastRatio`，不要另写一份。
- 删除逐项错峰延迟时，`AppShell.test.ts` / `StatCard.test.ts` 里若有依赖延迟的断言一并清掉。

## 已知取舍

- 主色偏离 02 的 `#1677ff`（4.10:1）到 `#1570F0`（4.56:1），以及新增 `--wm-color-primary-strong` 承接淡染底上的文字（02 的 `#1677ff` on `#e8f1ff` 只有 3.61:1）——保真到「同色相、满足门槛」比保真到某个十六进制值更重要。同理 tag 文字色不取 02 的 `--tag1-fg` / `--tag3-fg`（3.51 / 3.19）。
- 不引入 02 的 `Bahnschrift` / `DengXian`：Windows 独占字体，其他开发机必然掉字。`--font-num` 的意图改用 `tabular-nums` 表达。
- 去掉 grain 噪点是本 slice 唯一「02 有而新前端不要」的视觉元素：它是全屏 `mix-blend-mode:overlay` 层，与 EP 弹层和 ECharts canvas 叠加会出现可见斑驳。
- 引入 Pinia 是重做的收益之一（35 个 SFC 的模块级单例 `ref` 是本 slice 要清掉的隐式全局态），代价是一个新运行时依赖。
