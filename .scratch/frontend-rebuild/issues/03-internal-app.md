# 03 — internal 应用重写（三栏骨架 + 七模块 + 三详情页）

**What to build:** 删掉 `apps/internal/src` 全部内容与全部 `*.spec.ts`，在 01 的 shared 地基上重写内部工作台：三栏骨架（侧栏 248 + 主区 + 右侧检查器 336，无检查器时塌为两栏）、02 语言的登录页、落地页、七个模块与三个详情页。工程装配（`package.json`、`vite.config.ts` 的 5174 端口与 `/api` 代理、`tsconfig.json`、`index.html`）不动。

本 issue 同时消化三处结构性债务：工单从风控监测的 tab 里拆成一级模块；「客户关系」从占位页实做到名下客户列表 + 开户；三个超 400 行的巨型文件（`ProfilePanel.vue` / `RiskMonitoringWorkspace.vue` / `AdvisoryReviewPage.vue`）按职责拆分。

**Blocked by:** 01 — shared 地基

**Status:** implemented

## 外壳与身份

- [x] 登录页（02 语言，整屏两栏）：**正确使用 `el-form` + `rules`**；登录后必须调 `GET /api/internal/auth/me` 拿到 `real_name` + `employee_role`，失败视为登录失败
- [x] `auth` store：tokens、`currentEmployee`、`login()` / `logout()` / `restoreSession()`；被动 401（`onUnauthorized` 清 token）时兜底跳登录
- [x] 外壳：`AppShell` + 侧栏底部 `sidebar-footer` 槽挂「今日风险预警 N 条待处置」小卡（`GET /api/internal/risk-alerts?status=未处理` 计数，三个角色都可见，**数字天然按角色可见范围收窄**；N=0 给空态文案而非隐藏；加载失败给「暂不可用」）
- [x] 顶栏左槽放面包屑（`当前模块 / 当前页面`），右槽放 `real_name · employee_role` 与页面级操作
- [x] `currentCustomer` store：`currentCustomerId` / `setCustomer()` / `clear()`。**命名纪律：不得叫「风险关注」**——那是 `CONTEXT.md` 的领域术语，已被 `GET /api/internal/risk-focus` 占用
- [x] 角色驱动导航：`visibleModules(role)` 与角色常量留在 `apps/internal/src/shell/modules.ts`，**不进 shared**
- [x] 角色不足时保留自己的 URL 与外壳、渲染 `ModuleForbidden`，不做重定向
- [x] 落地页 `/`：只渲染登录者可见模块的入口卡（图标 + 名称 + 描述），**零业务数据聚合**；无可见模块时给空态说明（正常页面，不是错误）

## 路由

| 路由 | 页面 | 可见角色 |
|---|---|---|
| `/` | 落地页 | 全部 |
| `/knowledge` | 知识库管理（文档管理 + 检索试验） | 全部 |
| `/data-analysis` | 数据分析 | 全部 |
| `/profile` | 客户画像 | 理财顾问 |
| `/advisory` | 投顾助手 | 理财顾问 |
| `/advisory/reviews/:draftId` | 审核页 | 理财顾问 |
| `/risk-monitoring` | 风控监测（预警列表 / 风险关注 / 规则管理 / 自然语言查询） | 全部 |
| `/risk-monitoring/alerts/:alertId` | 预警详情 | 全部（处置按角色门控） |
| `/work-orders` | 工单管理 | 全部 |
| `/work-orders/:workOrderId` | 工单详情与流转 | 全部（流转按角色门控） |
| `/customer-relations` | 客户关系 | 客户经理 |
| `/login` | 员工登录 | public |

- [x] 七个模块的导航顺序：知识库管理 / 数据分析 / 客户画像 / 投顾助手 / 风控监测 / 工单管理 / 客户关系
- [x] 三角色的可见项数：理财顾问 6、客户经理 5、风控专员 4

## 右侧检查器

- [x] 壳层提供 `inspector` 插槽；**画像 / 投顾助手 / 审核页 / 工单详情**注入客户检查器，**风控监测 / 工单列表**注入模块自己的筛选摘要，**知识库 / 数据分析 / 落地页**不注入 → 第三栏塌为两栏
- [x] 客户检查器四块：客户卡（姓名、分层、AUM、开户时间）、风险画像（等级大字 + 呈现文案 + 置信度 + 维度条）、当前持仓（前 3 条 + 合计）、风险预警卡
- [x] 数据来源：`GET /api/internal/customers/{id}/profile`（`real_name` / `tags[]` / `judgement`）+ `GET /api/internal/customers/{id}/assets`（`total_market_value` / `holdings[]`）+ `GET /api/internal/risk-alerts`（**接口无 `customer_id` 过滤，拉列表后按 `customer_id` 前端过滤**）
- [x] 三块并发拉取，各自独立 loading 与失败态；单块失败只让那一块显示「暂不可用」，不整栏报错
- [x] **维度条按接口实际给的 tags 画**：`tags[].tag_key` / `value` / `confidence` / `source` 里没有的维度就不画条，**不编造数值**

## 七模块

- [x] 知识库管理：文档上传（FAQ / 产品 / 政策，multipart 带 `knowledge_type` 与可选 `title`）、列表筛选、状态与阶段标签、删除、处理中轮询；检索试验（`POST /api/internal/knowledge/search`）按兜底阈值分上下区、命中卡片分级
- [x] 数据分析：自然语言提问 → 解读 + 表格 + SQL 折叠 + CSV 导出 + 截断提示；历史查询复用；示例问题
- [x] 客户画像：左侧客户列表 + 画像主体 + **目标配置 vs 实际配置对比图**（`toComparisonBarOption`，固定类别序）+ 持仓关系图（`toGraphOption`，按需展开基金经理）+ 手工修正标签（`source=顾问` 时仅理财顾问可写）。**拆成「客户列表 / 画像主体 / 配置对比图 / 图谱面板」四块**，单文件回到 400 行内
- [x] 投顾助手：待生成请求 / 待审核 / 已审核记录三段；生成方案（选 tilt）；入口跳审核页
- [x] 审核页（`AdvisoryReviewPage` 拆分后）：AI 原稿与顾问定稿并排/切换可见；勾选保留与改配置；警告提示；放行（`release`）与驳回（`reject`，**理由必填**）；留言；403 → 无权查看。**这是护栏 5「未审核内容不可送达」在前端的落点**
- [x] 风控监测：预警列表（等级 / 状态 / 时间筛选，按角色收窄）、风险关注（只读）、规则管理（启停 + 阈值，风控专员专属写操作）、自然语言查询（`POST /api/internal/risk-monitoring/query`）。**工单列表从本模块移出**
- [x] 预警详情：规则命中依据、客户、交易、历史；排除 / 升级 / 派生工单三个动作**共用理由且理由必填**，按 `canDispose` / `canDeriveWorkOrder` 门控，非风控专员只显示说明
- [x] 工单管理（新模块）：列表（状态 / 客户 / 来源预警筛选）+ 外部工单创建 + 详情与流转（接单 / 办结需结论 / 关闭），按 `canHandleWorkOrder` 门控
- [x] 客户关系（**从占位页实做**）：名下客户列表（`GET /api/internal/customers`，后端已按归属收窄）+ 开户表单（`POST /api/internal/customers`）。字段：`username` / `password` / `real_name` / `id_number` / `phone` / `customer_level` / `annual_income_range` / `total_assets` / `investment_experience` / `target_allocation?` / `product_preference?`；`el-form` + `rules` 校验；`customer_level` 取值必须是**客户分层**的规范写法（普通 / 金卡 / 白金 / 钻石 / 私行）；成功后备注名下客户列表
- [x] 模块描述删掉「服务记录」——后端无该接口，不能承诺

## 测试（只覆盖合规呈现面与权限门控）

- [x] 审核流：AI 原稿与顾问定稿两版本分别可见；放行与驳回各自走通；**驳回理由为空时提交被拒**
- [x] 角色门控：七模块 × 三角色，不足角色渲染 `ModuleForbidden` 且 URL 与外壳保留；处置/流转动作对非风控专员不可见
- [x] 身份域隔离：internal 的 token 不出现在 customer 的请求里
- [x] 登出入口在壳层恒在（任何角色、任何路由）
- [x] `pnpm --filter @wealth/internal typecheck` 与 `test` 全绿

## 实现记录

- **客户卡的「开户时间」没有画**：`GET /api/internal/customers` 只有 `id` / `username` / `real_name` / `customer_level` / `risk_level`，
  没有任何接口暴露 `opened_at`（只有开户响应里有）。按「接口给什么画什么」，客户卡画姓名、分层、AUM 与持仓数，
  不补一个来源不明的开户时间。这是本 issue 与检查器 mockup 之间唯一缺的字段。
- **检查器多了一次 `GET /api/internal/customers`**：同样是「分层」没有单客户来源。四块内容对应四次并发拉取
  （画像 / 资产 / 预警 / 目录），各自独立 loading 与失败态；客户卡只在三路全失败时显示「暂不可用」，
  目录那一路失败只让分层显示「暂不可用」。
- **「风险画像」块的综合置信度是各标签置信度的均值**，界面上写明「各标签均值」。接口没有单一置信度字段，
  均值是透明聚合而不是编造；维度条按接口实际返回的 `tags[]`（`key` / `label` / `value` / `source` / `confidence`）逐条画，
  没有给的维度不画条。**注意字段是 `tags[].key`，不是 issue 里写的 `tag_key`**（`conflict_records[]` 才用 `tag_key`）。
- **`/risk-monitoring/alerts/:alertId` 注入的是客户检查器**，不是模块的筛选摘要：issue 枚举了哪些页面注入哪一种，
  预警详情不在其中；但一张预警属于某位客户，在详情页放「筛选摘要」没有意义。定为客户上下文，记录在此供复核。
- **规则管理补了阈值调整**：issue 检查项写的是「启停 + 阈值」，现状只有启停。阈值改动走
  `PATCH /risk-rules/{id}/threshold`，与后端一致地要求非空理由（没有理由不发请求）。
- **驳回按钮保持现状的 `:disabled`，handler 里再挡一次**：空理由既点不动，也不会因任何路径绕过 disabled 而发出请求。
- **`api/http.ts` 显式传 `fetchImpl: (input, init) => fetch(input, init)`**：共享包的 `createHttpClient` 在构造时按值捕获 `fetch`，
  会让运行时替换（测试替身）在模块加载后失效。改成调用时取全局那一份；这是 internal 这一侧的选择，shared 不动。
- **`stores/auth` 把「拿到空身份」也算登录失败**：`GET /auth/me` 返回 200 但 `data` 是空壳时，原先会留下一个
  「已登录但没有角色」的会话，工作台会渲染成空导航。现在身份缺失与请求失败同等处理——清令牌、视为登录失败。
- **检查器的注入机制**：壳用 provide/inject 把 `inspector` / `topbar-actions` 两个注册通道交给页面（`shell/pageSlots.ts`），
  没有页面注册时 inspector 为空，AppShell 据此塌成两栏——三栏与否仍然只有一个来源，不额外传 variant。
- **「手工修正标签仅理财顾问可写」由两道闸门保证，界面上不再加一个重复判断**：`/profile` 模块本身只对理财顾问开放
  （角色不足渲染 `ModuleForbidden`），写入的 `source` 固定为「理财顾问手工修正」，后端还会按该 source 再挡一次 403。
  在标签瓦片上再加一个 `v-if="isAdvisor"` 是永远为真的死代码。
- **拆分后的文件规模**：最大的单文件 380 行（`inspector/CustomerInspector.vue`），三个巨型文件分别落到
  `profile/`（客户列表 / 画像主体 / 标签 / 历史 / 对比图 + `graph/` 图谱面板）、`risk/`（四个页签各一件）、
  `advisory/`（两版本面板 / 审核决定 / 留言），全部回到 400 行内。

## 落地要点

- 只换骨架与视觉 + 三处结构债务（工单拆模块、客户关系实做、巨型文件拆分），**其余页面的字段与流程与现状一致**。任何「顺手优化一下交互」的冲动都停下来，那是另一个 issue。
- 检查器的四个维度条是本 issue 唯一需要先读接口再动手的地方：先看 `profile` 返回的 `tags[].tag_key` 实际有哪些，再决定画几条。
- 「今日风险预警」小卡是对 `GET /api/internal/risk-alerts` 的**一次额外调用**（外壳层），与风控监测页自己的列表调用互不共享缓存；这是可接受的代价，不要为它引入全局查询缓存。
- 图表只有两处（画像的对比图、图谱面板的力导向图）+ 工单/预警内的表格，全部沿用既有 `chart/*`，不新造形状函数。

## 已知取舍

- 工单拆成一级模块后，风控监测从 5 个 tab 降到 4 个，「处置完预警去办工单」变成跨模块跳转。换来的是工单不再是预警的附属物（它可来自客户投诉与转人工），以及 `RiskMonitoringWorkspace.vue` 从 567 行回到 400 行内。
- 客户关系模块的「开户」是对 spec Q5「功能对等」的**显式破例**（Q9 批准）：现有前端从未暴露过 `POST /api/internal/customers`。验收时要能单独指认这一项，不能混在重写里。
- 检查器的「某客户预警」靠前端过滤而非后端过滤（接口无 `customer_id` 参数，加参数属于后端改动、本 slice Out of Scope）。预警量大时这一块会偏慢，届时再议。
