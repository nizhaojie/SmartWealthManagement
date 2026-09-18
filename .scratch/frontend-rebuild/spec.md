# 双前端从零重做（企业浅色骨架 · 02 视觉语言）

Status: ready-for-agent

前置：无——后端全部能力已实现（29 个 router、约 90 条接口），本 slice 不依赖任何未完成的后端工作。

**取代**：`.scratch/frontend-restyle/spec.md`。那份 spec 决定的两件事在本 slice 被推翻：① 令牌主色取 `#1F6FEB` 与单形态外壳（220px 侧栏 + 顶栏）；② 「只换皮、不动信息架构」的纪律。本 slice 是重写而非换皮。

## Problem Statement

两个前端现在是「功能跑通了、但结构与视觉都是将就」的状态：

- **信息架构留有空洞**。客户经理的「客户关系」模块渲染的是 `ModulePlaceholder`（`apps/internal/src/shell/ModuleView.vue:32`）——零实现，而它的模块描述却承诺了「查看归属客户的基本信息与**服务记录**」，服务记录在后端根本不存在。工单被塞在风控监测的第五个 tab 里，而工单可以来自预警之外的源头（客户投诉、转人工），它从来不是预警的附属物。
- **主链路的可见面缺最后一环（本 slice 已知而不闭）**。`GET /api/customer/advisory/plan`（顾问定稿，即「唯一允许送达客户的版本」）**前端没有任何页面消费它**（`apps/customer/src/advisory/api.ts` 只有提交与列表两个函数，全仓检索 `advisory/plan` 零命中）。客户能提交方案请求、能看到请求状态，唯独看不到顾问最终放行的方案。「投顾内容必须经审核后才能送达客户」这条核心约束，在界面上终止于一个没人调用的端点。这是真问题，但**不在本次重做的范围内**（Q17），见 Out of Scope 与 Further Notes。
- **视觉状态是上一轮的临时产物**。`frontend-restyle` 交付的浅色骨架是照着几张仪表盘参考图做的风格致敬，与目标形态（`02-企业浅色.html`）不同源：外壳是双栏而非三栏、没有右侧检查器、没有客户上下文常驻区。
- **状态是隐式全局**。35 个 SFC 全部靠模块级单例 `ref`（`apps/internal/src/auth/store.ts` 等）共享状态，没有显式 store；引入「当前客户」这类跨页面状态后，单例 ref 会退化成隐式耦合。
- **测试与实现的比例失衡**。36 个 spec 里有大量「挂载后断言某文案出现」的模板化用例，而合规呈现面（引用可点、适当性提示、两版本留存、审核放行）的断言并不比它们多。

## Solution

按 `02-企业浅色.html`（风格 02 · 企业浅色，Ant Design 风企业级中后台）从 0 重写两个前端，`apps/*/src` 全量删除重建，工程装配（目录、端口、workspace 声明、后端 CORS）一字不改。

- **视觉语言整体换代**：白底蓝调、发丝线、三档圆角、卡片承托、248px 侧栏 + 60px 顶栏、KPI 卡与进度条的排版层级。主色取同色相且满足对比度门槛的档位（见「设计令牌层」），去掉全屏 grain 噪点层与卡片 hover 上浮，字体回落到系统栈。
- **internal 采用三栏骨架**，右侧检查器常驻「当前客户」上下文（客户卡、风险画像、当前持仓、风险预警）；无客户上下文的页面第三栏塌陷为两栏。
- **customer 采用两栏骨架**，主区限宽居中——客户侧不可见预警等级与处置动作（**客户可见视图**边界）。
- **信息架构只动一处**：工单管理从风控监测中拆为一级模块。
- **状态显式化**：引入 Pinia，每端一个 `auth` store，internal 另有「当前客户」store。
- 后端零改动；`packages/shared` 的构建期边界闸门保留。

## 访谈结论清单（grill-with-docs，2026-09-18，两轮共 16 问）

### 第一轮

| # | 决定 |
|---|---|
| Q1 | 技术栈**维持 Vue 3 + Element Plus + ECharts**。02 提供的是一套视觉语言，不是组件库规格；用 EP + 令牌实现这套观感，只有少数几个展示件需要自绘。ADR-0001 不动。 |
| Q2 | **原地重建**：删 `apps/customer/src`、`apps/internal/src` 全部内容与全部 `*.spec.ts`，保留 app 目录、`package.json`、`vite.config.ts`、`tsconfig.json`。端口仍 5173/5174，后端 CORS 白名单不动。旧代码留在 git 历史里，不另开分支。 |
| Q3 | **保留并扩充 `packages/shared`**，边界闸门保留。02 里无业务语义的展示件正是 shared 的合法内容。 |
| Q4 | **三栏只做 internal 的骨架**，右侧检查器为 internal 的「当前客户」常驻区；customer 两栏限宽。 |
| Q5 | **功能对等 + 只动一处信息架构**（工单拆为一级模块）。后端有接口而前端从未有页面的能力列进 Out of Scope。 |
| Q6 | **照搬色彩与形状语言，不照搬全部令牌值**：主色取满足 4.5:1 的同色相档位；去掉 grain 与 hover 上浮；字体回落系统栈。布局骨架、三档圆角、发丝线、卡片阴影、排版层级全部照搬。 |
| Q7 | **引入 Pinia**。 |
| Q8 | **只测合规呈现面与权限门控**，不逐页复制模板化 spec；保留令牌对比度测试。 |

### 第二轮

| # | 决定 |
|---|---|
| Q9 | internal 导航保留 7 个模块（含「客户关系」），并把客户关系**实做到后端能支撑的范围**：名下客户列表 + 开户表单，删掉描述里无接口支撑的「服务记录」。这是对 Q5 的一处显式破例。 |
| Q10 | 检查器内容**由页面经 `inspector` 具名插槽注入**；internal 用 Pinia 维护全局「当前客户」，画像/投顾/审核/工单详情注入客户检查器，风控监测与工单列表注入模块自己的摘要，其余页面无检查器 → 第三栏塌陷为两栏。侧栏底部「今日风险预警 N 条待处置」小卡保留，三角色均可见，N=0 给空态文案而非隐藏。 |
| Q11 | shared **净增 2 个、重做 3 个**：重做 `AppShell`、`SectionCard`→`PanelCard`、`StatCard`；新增 `MeterBar`、`PageHeader`。`CiteChip` 留 customer 应用内。 |
| Q12 | **图表沿用现状**：`chart/palette.ts`、`chart/options.ts`、`chart/ChartFrame.vue` 全部不动，只把 `ChartFrame` 的容器样式并入 02 卡片语言。 |
| Q13 | **自建 02 语言的登录页**：整屏两栏（左品牌区 + 右登录卡），纯 CSS 无图片资源，两端各一张。正确使用 `el-form`。 |
| Q14 | **三刀交付**：① shared 地基 → ② customer（登录页 + 四页）→ ③ internal（七模块 + 三个详情页 + 落地页）。每刀收尾跑 `pnpm typecheck` + `pnpm test` 并真机走查。 |
| Q15 | 新写本 spec 并拆三份 issue；**不新增 ADR**；`CONTEXT.md` **零改动**；更新 `docs/roadmap.md`。 |
| Q16 | `pnpm dev` 改为起 backend + customer + internal；其余装配（端口、`/api` 代理、`pnpm test` 顺序、`scripts/dev-backend.mjs`、`start-all.bat`）全部维持。 |
| Q17 | 客户侧**不新增**「我的方案」页。`GET /api/customer/advisory/plan` 在本 slice 中仍无前端消费方——这是被明确接受、记录在案的缺口，不是遗漏。 |

## 关键事实基线

以下是本 slice 的决策依据，实现时可直接引用，不必重新检索。

| 事实 | 依据 |
|---|---|
| 六个依赖容器全部 healthy（MySQL 3307 / Milvus 19531 / Redis 6380 / Neo4j 7688+7475 / MinIO 9001 / etcd 12379）。上一轮「走查被环境阻塞」的记录不再适用。 | `docker ps`，2026-09-18 |
| 后端 CORS `allow_origins` 硬编码 `http://localhost:5173`、`http://localhost:5174`，无 `allow_credentials`。换端口就要改后端。 | `backend/app/main.py:87-92` |
| 统一响应信封 `{code, message, data, trace_id}`；`code≠200` 由 shared 的 `unwrap` 抛 `ApiError`；401 触发 `onUnauthorized` 回调清 token。 | `packages/shared/src/http.ts` |
| SSE 协议：`POST /api/customer/chat/stream`，帧为 `event:` / `data:` 两行，`event: done` 携带定案答案与引用，其余帧携带 `delta`。**推流过程不做任何决策**（整轮先跑完再逐字转帧）。 | `backend/app/api/chat.py:87-109`、`apps/customer/src/chat/api.ts` |
| `GET /api/internal/risk-alerts` **无 `customer_id` 过滤参数**（只有 `alert_level` / `status` / `created_from` / `created_to`）。要做「某客户的预警」只能拉列表后前端过滤。 | `backend/app/api/risk_alerts.py:41-49` |
| 预警读权限是 `current_employee`（三角色都可读），**客户经理的可见范围天然收窄到名下客户**；三个写操作（排除/升级/派生工单）只放开给风控专员且理由必填。 | `backend/app/api/risk_alerts.py:1-6` |
| 工单读权限 `current_employee`（客户经理限名下），写操作只放开给风控专员。`GET /api/internal/work-orders` 支持 `status` / `alert_id` / `customer_id` 过滤。 | `backend/app/api/work_orders.py` |
| mockup 顶栏的「导出推荐报告」**后端无对应接口**。 | 无导出路由 |
| 边界闸门 `check-boundary.mjs` 在 build 时词法扫描 `packages/shared/src`，命中业务词即中断构建。词表含 `客户画像` / `风险承受等级` / `目标配置` / `实际配置` / `产品风险等级` / `工单` / `预警分级` / `AI原稿` / `顾问定稿` / `适当性匹配` / `候选池` / `投顾内容` 等。 | `packages/shared/scripts/business-semantics-guard.mjs` |
| `需求量文档-修改版.html` 无任何界面/布局章节（只写「Streamlit/Gradio 演示界面」），`02-企业浅色.html` 是唯一视觉依据。 | 全文检索 |
| 旧前端规模：customer 42 文件约 3530 行（13 个 `.vue`）、internal 68 文件约 9020 行（22 个 `.vue`）、shared 25 文件约 1950 行。`ProfilePanel.vue`(621) / `RiskMonitoringWorkspace.vue`(567) / `AdvisoryReviewPage.vue`(407) 是单文件超 400 行的三个，重做时必须拆分。 | 逐文件统计 |

## Implementation Decisions

遵循 `docs/adr/`。本 slice 直接受 ADR-0001（Vue3 + Element Plus）、ADR-0003（shared 边界）、ADR-0009（合规护栏测试）约束。

### 设计令牌层（`packages/shared`）

CSS 自定义属性仍是唯一事实源（`:root`），TS 侧只做只读镜像供 ECharts 等 JS 取色场景使用。令牌值以 02 为基准，**偏离处标注原因**。

**色彩**

| 令牌 | 值 | 对白底对比度 | 与 02 的关系 |
|---|---|---|---|
| `--wm-color-primary` | `#1570F0` | 4.56:1 | **偏离**。02 的 `#1677ff` 只有 4.10:1，跌破既有 4.5 门槛。同色相压深一档，肉眼几乎不可分辨。 |
| `--wm-color-primary-strong` | `color-mix(in srgb, primary 78%, black)` | 5.96:1（在 primary-tint 上） | **新增**。02 的导航激活项是 `--accent-text #1677ff` on `--accent-soft #e8f1ff`，实测 **3.61:1**，不达标。淡染底上的文字一律走这个令牌。 |
| `--wm-color-primary-tint` | `#E9F1FF` | — | 02 的 `--accent-soft`。 |
| `--wm-color-up` | `#C81E1E` | 5.74:1 | 维持（红涨绿跌，中国金融惯例）。02 未定义涨跌。 |
| `--wm-color-down` | `#1E7A46` | 5.35:1 | 维持。 |
| `--wm-color-success` | `#1E7A46` | 5.35:1 | **偏离**。02 的 `--tag1-fg #0f9d58` 只有 3.51:1。 |
| `--wm-color-warning` | `#B45309` | 5.02:1 | **偏离**。02 的 `--tag3-fg #d97706` 只有 3.19:1。 |
| `--wm-color-danger` | `#D4380D` | 4.80:1 | 采用 02 的 `--danger`（达标）。 |
| `--wm-text-primary` | `#1F2329` | 14.6:1 | 02 的 `--text`。 |
| `--wm-text-muted` | `#6B7688` | 4.59:1 | 02 的 `--muted`，刚过门槛。 |
| `--wm-text-placeholder` | `#A3ACBD` | 2.28:1 | 02 的 `--faint`。**豁免**：以注释声明仅限 placeholder 与装饰，禁用于有意义文字。 |
| `--wm-bg-page` | `#F4F6FA` | — | 02 的 `--bg`。 |
| `--wm-bg-card` / `--wm-bg-sidebar` | `#FFFFFF` | — | 02 的 `--surface` / `--side-bg`。 |
| `--wm-bg-subtle` | `#FAFBFC` | — | 02 的 `--surface-2`。 |
| `--wm-border` | `#E6E9F0` | — | 02 的 `--line`。 |
| `--wm-border-hairline` | `#EEF1F6` | — | 02 的 `--track`（同时用作进度条底色）。 |
| `--wm-bg-user-bubble` | `#E8F1FF` | 13.9:1（配 `--wm-text-primary`） | 02 的 `--user-bg`。 |

Tag 浅底沿用 02 的 `#E7F7EE` / `#E8F1FF` / `#FFF4E5`，但**文字色走 success / primary-strong / warning 令牌**，不取 02 的 `--tag*-fg`。

**形状与材质**

- 圆角三档采用 02：`6px` / `8px` / `10px`（原 4/8/12 废弃）。
- 卡片阴影采用 02：`0 1px 3px rgba(16,24,40,.06), 0 1px 2px rgba(16,24,40,.04)`；浮层阴影 `0 10px 26px rgba(16,24,40,.12)`（原 `0 4px 16px` 废弃）。
- 间距刻度维持 4/8/12/16/24/32。
- **去掉** `body::before` 的全屏 grain 噪点层（`mix-blend-mode:overlay`，与 EP 弹层和 ECharts canvas 叠加时产生可见斑驳）。
- **去掉**卡片 hover 上浮（`transform:translateY(-3px)`），保留边框色过渡。
- **保留** 02 的 `focus-visible` 轮廓、自定义滚动条、`::selection`、面板顶部的发丝渐变线（`.panel::after`）。

**字体与数字**

- `--wm-font-family: system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`。**不引入** 02 的 `Bahnschrift` / `DengXian`（Windows 独占，其他机器必然掉字）。
- `--wm-font-mono: Consolas, "DejaVu Sans Mono", monospace`（SQL 与代码块）。
- 02 的 `--font-num` 意图用 `font-variant-numeric: tabular-nums` 表达，不另立字体族。凡是数字对齐场景（KPI、金额、表格数值、匹配度）统一挂 tabular-nums。
- 动效：保留 `wbRise` 载入浮现与 `wbPulse` 预警脉冲，`@media (prefers-reduced-motion: no-preference)` 包裹。**去掉**逐项 `nth-child` 错峰延迟——列表长度是动态的，硬编码 nth-child 是伪动效。

**布局常量**

- `--wm-sidebar-width: 248px`、`--wm-topbar-height: 60px`、`--wm-inspector-width: 336px`（均取 02）。
- `--wm-content-max-width: 1080px`（customer 主区限宽居中，02 未给，为本 slice 新增）。
- 窄屏（<1280px）侧栏收窄到 220px、检查器 300px；<1200px 第三栏塌陷。**仅此一条响应式规则**，不做移动端适配。

### 骨架

`AppShell`（shared）提供两种形态，**由 `inspector` 插槽是否存在自动决定**，不额外传 variant——避免插槽与 variant 两个来源不一致。

```ts
props: {
  navItems: { key: string; label: string; icon?: Component; badge?: number }[]
  activeKey: string
  brandSubtitle?: string        // 品牌区副标题（"Wealth Copilot" 位）
}
slots: {
  brand           // 品牌区内容
  topbar-left     // 面包屑 / 页面标题
  topbar-right    // 页面级操作
  default         // 主区
  inspector       // 右栏；不提供则壳渲染两栏
  sidebar-footer  // 侧栏底部小卡（internal 放「今日风险预警」）
}
emits: { select: [key: string]; logout: [] }
```

- **登出入口在壳层恒在**：任何角色、任何路由可见可用（沿袭 `internal-workbench-shell` 的教训，有既有测试覆盖）。
- 导航 badge 用 `--wm-color-danger` 淡底（02 的 `.nav-item em`），值由应用从真实接口算出后注入——壳不认识「预警」是什么。
- customer 用 `AppShell` 无 `inspector` 插槽 + 主区 `--wm-content-max-width` 居中。

### Pinia

新增依赖 `pinia`（两个应用各一份实例，不共享 store）。store 划分：

| 应用 | store | 状态 |
|---|---|---|
| customer | `auth` | `tokens`、`isAuthenticated`、`login()` / `logout()` / `restore()` |
| customer | `chat` | 当前会话的消息列表（**不跨登录延续**——重新登录即新会话） |
| internal | `auth` | `tokens`、`currentEmployee`、`login()` / `logout()` / `restoreSession()` |
| internal | `currentCustomer` | `currentCustomerId`、`setCustomer()`、`clear()` |

> **命名纪律**：这个全局态叫「当前客户」，**不得叫「风险关注」**。`CONTEXT.md` 里 **风险关注** 是一个精确的领域术语（一个 Agent 留给其他 Agent 的提示记录），而 `GET /api/internal/risk-focus` 已占用该名字。壳与 store 一律用 `currentCustomer`。

### 路由与模块

**internal**（7 模块 + 落地页 + 3 详情页）

| 路由 | 模块/页面 | 可见角色 |
|---|---|---|
| `/` | 落地页（模块入口卡，零数据聚合） | 全部 |
| `/knowledge` | 知识库管理（文档管理 + 检索试验） | 全部 |
| `/data-analysis` | 数据分析 | 全部 |
| `/profile` | 客户画像 | 理财顾问 |
| `/advisory` | 投顾助手（待生成请求 / 待审核 / 已审核记录） | 理财顾问 |
| `/advisory/reviews/:draftId` | 审核页（AI 原稿 vs 顾问定稿） | 理财顾问 |
| `/risk-monitoring` | 风控监测（预警列表 / 风险关注 / 规则管理 / 自然语言查询） | 全部 |
| `/risk-monitoring/alerts/:alertId` | 预警详情 | 全部（处置表单按角色门控） |
| `/work-orders` | 工单管理（列表 + 外部工单创建） | 全部 |
| `/work-orders/:workOrderId` | 工单详情与流转 | 全部（流转按角色门控） |
| `/customer-relations` | 客户关系（名下客户列表 + 开户） | 客户经理 |
| `/login` | 员工登录 | public |

角色的「可见模块」判定保留在 `apps/internal/src/shell/modules.ts`（`visibleModules(role)`），**不进 shared**。角色不足时保留自己的 URL 与外壳、渲染 `ModuleForbidden`，不做重定向。

`RiskMonitoringWorkspace.vue` 原含 5 个 tab，拆分后保留 4 个；工单列表与详情移入新模块。拆分是为了让单文件回到 400 行以内。

**customer**（两栏骨架）

| 路由 | 页面 | 说明 |
|---|---|---|
| `/login` | 客户登录 | public |
| `/chat` | 智能对话 | SSE 流式 + 可点击引用角标 |
| `/risk-assessment` | 风险测评 | 已评测 → 结果页；否则 → 问卷页（两个子路由或一个工作区组件，沿用现结构） |
| `/products` | 产品筛选 | 筛选 + 详情 + 提交方案请求 + 请求列表。**模块名不改为「产品中心」**——「产品筛选」是 `CONTEXT.md` 的规范用词，它陈述「符合条件的产品有哪些」而不评价适配性，改名会漂移语义。 |
| `/assets` | 我的资产 | 持仓 + 实际配置 donut + 风险等级分布 bar + 持仓穿透 + 交易流水 |

客户侧导航共 4 项（Q17 确认不新增「我的方案」页）。

### 客户检查器（internal 右侧栏）

四块内容对应 mockup，数据来源全部是既有接口：

| 区块 | 数据来源 |
|---|---|
| 客户卡（姓名、分层、AUM、开户时间） | `GET /api/internal/customers/{id}/profile`（`real_name`）+ `GET /api/internal/customers/{id}/assets`（`total_market_value`、`holding_count`） |
| 风险画像（等级大字、呈现文案、置信度、四维条） | `GET /api/internal/customers/{id}/profile` 的 `tags[]`（含 `confidence` 与来源）+ `judgement` |
| 当前持仓（前 3 条 + 合计） | `GET /api/internal/customers/{id}/assets` 的 `holdings[]` |
| 风险预警卡 | `GET /api/internal/risk-alerts`（**接口无 `customer_id` 过滤**，拉列表后按 `customer_id` 前端过滤；列表本身已按角色收窄） |

- 检查器**懒加载**：三个接口并发拉取，各自有独立 loading 与失败态；单块失败只让那一块显示「暂不可用」，不整栏报错。
- `GET /api/internal/customers/{id}/profile` 的 `tags` 结构是实现时第一个要读的东西——`tags[].tag_key` / `value` / `confidence` / `source` 的实际取值决定四维条怎么画。**不新造后端字段**，接口给什么画什么；接口不提供的维度就不画条（mockup 的「流动性需求」若在 tags 中不存在，则少一条而不是编一个值）。

### 开户表单（客户关系模块）

字段取自 `POST /api/internal/customers` 的 `OpenAccountRequest`：`username` / `password` / `real_name` / `id_number` / `phone` / `customer_level` / `annual_income_range` / `total_assets` / `investment_experience` / `target_allocation?` / `product_preference?`。

- 用 `el-form` + `rules` 做前端校验（现有登录页缺 `el-form` 是上一轮的坑，不再重复）。
- **`customer_level` 取值必须是 `CONTEXT.md` 的**客户分层**（普通/金卡/白金/钻石/私行），不引入 mockup 的「金牌/资深」那类不存在的分级。**
- 开通成功后刷新名下客户列表。「名下客户」即 `GET /api/internal/customers` 在当前登录者名下的部分（后端已按归属收窄）。

### 视觉纪律

- **令牌纪律**：SFC 的 scoped style 不得出现裸色值与裸间距（1px 细线等极少数例外需在注释里说明理由）。靠 review 执行，**不引入 stylelint**（仓库无 CSS lint 工具链，为一条规则加一套工具是本末倒置）。
- EP 组件内部着色（tag 浅底、按钮 hover 派生态）维持库默认，仅通过 `--el-color-primary*` 映射主题化。本次不做 EP 组件的无障碍加固。
- 涨跌数字（`profit_loss` / `profit_ratio`）按红涨绿跌着色，**颜色只出自 `--wm-color-up/down`**，应用侧按符号挂类、不传色值。

### 破例清单（超出 Q5「功能对等」的两处，逐条单列）

1. **工单管理拆为一级模块**——由 Q5 自身批准（信息架构调整），不视为破例之外的新增功能：工单列表、详情、流转表单全部已存在，只是换了归属与 URL。
2. **客户关系模块实做「名下客户列表 + 开户」**——Q9 批准的显式破例。它把后端的 `GET`/`POST /api/internal/customers` 第一次接到界面上。模块描述删掉「服务记录」（无接口，不能承诺）。这一项在验收时要能单独指认。

## Testing Decisions

不新增测试 seam，沿用既有 vitest 组件挂载 + 纯函数测试模式。**只覆盖合规呈现面与权限门控**（Q8）——逐页复制「挂载后断言文案出现」的模板化用例收益低于成本。

必测清单：

- **引用角标可点可定位**（customer 对话页）：回答中的 `[n]` 角标点击后能定位到对应引用（文档标识 + 段落位置）。这是客服链路的合规呈现面，不许为风格牺牲可点性。
- **适当性提示**（customer 产品筛选 / 候选池）：C4 客户可购 R1–R4 的说明存在，越级产品不出现在列表里。
- **两版本留存与审核动作**（internal 审核页）：AI 原稿与顾问定稿分别可见；放行与驳回各自走通，**驳回理由为空时提交被拒**。
- **角色门控与 403**（internal 七模块 × 三角色）：不足角色时渲染 `ModuleForbidden` 且 URL 与外壳保留；风控专员专属的处置动作对其他角色不可见。
- **SSE 帧解析**（customer 对话）：`event: done` 携带答案与引用、`data:` 帧携带 `delta`，异常走 `onError`。
- **身份域隔离**：customer 的 token 不会出现在 internal 的请求里，反之亦然（两个 localStorage key 不同、两个 http client 实例不共享）。这是 ADR-0009 护栏 2 在前端的落点。
- **shared 层**：令牌对比度（文本类与涨跌 ≥ 4.5:1，`--wm-text-placeholder` 以注释豁免并限定用途）；`AppShell` 两栏/三栏两形态与「登出入口恒在」；`MeterBar` / `StatCard` 的 accent 枚举约束；`check-boundary.mjs` 边界闸门测试保持通过。
- `pnpm typecheck` 与 `pnpm test` 每刀收尾必须全绿。

无视觉回归工具（仓库现状），以手工走查清单替代。

## Out of Scope

- **后端任何改动**。包括：新增「导出推荐报告」接口（mockup 顶栏有、后端无）、给 `GET /api/internal/risk-alerts` 加 `customer_id` 过滤（检查器改为前端过滤）、给 `GET /api/internal/customers` 补「服务记录」。
- **补齐后端已有、前端从未有页面的接口**：会话归档 `GET /api/internal/conversations`、调试与降级留痕 `GET /api/internal/traces/*`、图谱重建与统计 `POST /api/internal/graph/rebuild` + `GET /api/internal/graph/stats`、风险规则变更历史 `GET /api/internal/risk-rules/{id}/changes`、`/api/agents`、`/api/health`、开户之外的客户管理能力。
- **客户侧「我的方案」页**（Q17）。`GET /api/customer/advisory/plan` 在本 slice 后仍无前端消费方；客户应用只做智能对话 / 风险测评 / 产品筛选 / 我的资产四页。关闭这个缺口需要另开一份 spec，理由是它引入的是「客户如何接收投顾内容」这个新问题（送达方式、查看留痕、过期与否），不是把已有页面换个样子。
- **暗色模式；移动端 / 完整响应式适配**（只做一条 <1280px / <1200px 的塌陷规则）。
- **真实数据聚合的 KPI 仪表盘**（沿袭 `frontend-restyle` 的排除；侧栏小卡是单一真实数字，不是仪表盘）。
- **重写图表体系**：`chart/palette.ts`、`chart/options.ts`、`chart/ChartFrame.vue` 的行为与色板不动。
- **EP 组件内部着色的无障碍加固**。
- **页面信息架构之外交互流程的调整**：只换骨架、换视觉、按 Q9 补客户关系模块，其余页面的字段与流程与现状一致。

## Further Notes

- **本 slice 是重写而非换皮**，因此与 `frontend-restyle` 的三条纪律冲突，显式记录以免后来读者困惑：① 那份 spec 的「只换皮、不动信息架构」在本 slice 不适用；② 其中的令牌值表（主色 `#1F6FEB`、圆角 4/8/12、侧栏 220px、单形态外壳）被本 spec 的设计令牌层整节取代；③ 那份 spec 的「复合组件恰好三个，不再多」被 Q11 的「净增 2 个、重做 3 个」取代。`frontend-restyle` 的 Status 已改为 `superseded-by frontend-rebuild`。
- **未新增 ADR 的判定**：ADR-0001 与 ADR-0003 在本 slice 中维持不变（Q1、Q3）；引入 Pinia 可逆、不满足 ADR 门槛（hard to reverse / surprising / real trade-off）。三条均记录于本文件。
- **Q17 是「决定不做」，不是「忘记了」**：`GET /api/customer/advisory/plan` 无前端消费方这一点在重做后依然成立，后来读者不要把它当成重做时漏掉的一页。`CONTEXT.md` 对 **顾问定稿** 的定义（唯一允许送达客户的版本）现在只由后端机制保证，界面无从体现——要补这一环时，先回答「客户在什么场景下看、看完留不留痕、放行后又改版了怎么办」，而不是先加一个页面。
- **`CONTEXT.md` 零改动**：本 slice 未产生任何领域术语。「当前客户」是 UI 状态而非领域概念，且刻意避开 **风险关注** 的命名（后者已被 `GET /api/internal/risk-focus` 占用）。开户表单的 `customer_level` 取值、产品筛选的模块名都直接沿用既有规范用词，未引入新词。
- **`docs/roadmap.md` 更新**：`### 收尾` 里的「前端视觉重构」一行改指向本 spec 与三份 issue。
- **可复用的既有资产**（重写时要主动保留，不要顺手重造）：`packages/shared/src/http.ts`（信封拆包 + 401 回调 + `postForm` 支持）、`tokenStore.ts`、`chart/*` 三件、`scripts/dev-backend.mjs`、两个 `vite.config.ts`、`check-boundary.mjs`。
- **重写时要主动拆分的三个巨型文件**：`ProfilePanel.vue`(621) / `RiskMonitoringWorkspace.vue`(567) / `AdvisoryReviewPage.vue`(407)。Q9 与工单拆分已经处理了后两个的成因（视图与业务编排混在一个文件、tab 过载），画像面板要拆成「客户列表 / 画像主体 / 目标与实际对比图 / 图谱面板」四块。
