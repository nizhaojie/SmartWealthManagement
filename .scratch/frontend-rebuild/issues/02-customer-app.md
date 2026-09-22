# 02 — customer 应用重写（两栏骨架 + 登录页 + 四页）

**What to build:** 删掉 `apps/customer/src` 全部内容与全部 `*.spec.ts`，在 01 的 shared 地基上重写客户应用：两栏骨架（侧栏 + 主区限宽居中，无右侧检查器）、02 语言的登录页、以及智能对话 / 风险测评 / 产品筛选 / 我的资产四页。工程装配（`package.json`、`vite.config.ts` 的 5173 端口与 `/api` 代理、`tsconfig.json`、`index.html`）不动。

客户侧是**客户可见视图**边界之内的一切：持仓、交易流水、风险测评结论、事实性内容。画像与服务记录在其之外，本应用不得请求。

**Blocked by:** 01 — shared 地基

**Status:** implemented

- [x] 登录页（02 语言，整屏两栏：左品牌区 + 右登录卡；纯 CSS 无图片资源）：**正确使用 `el-form` + `rules`**，失败给内联提示而非 toast；品牌文案「智能财富管家」
- [x] 登录成功写入 `auth` store 的 tokens（沿用既有 localStorage key 语义），登出调 `POST /api/customer/auth/logout` 并清 store
- [x] 路由：`/login`（public）、`/chat`、`/risk-assessment`、`/products`、`/assets`；非 public 且未登录 → `/login`，已登录访问 public → `/chat`
- [x] 外壳：`AppShell` 不提供 `inspector` 插槽，主区挂 `--wm-content-max-width` 居中；导航 4 项（智能对话 / 风险测评 / 产品筛选 / 我的资产）配 EP 图标
- [x] 智能对话页：`POST /api/customer/chat/stream` 的 SSE 流式增量渲染（`fetch` + `body.getReader()` 按 `\n\n` 切帧，不用 `EventSource`；`event: done` 携带答案与引用、其余帧携带 `delta`）
- [x] **引用角标**：回答中的 `[n]` 渲染为可点击角标，点击后展示 `title` / `source_file` / `heading_path`；检索不到依据时的兜底话术与人工热线原样保留
- [x] 会话消息放在 `chat` store，**不跨登录延续**（重新登录即新会话）；滚动与 composer 交互对齐 02
- [x] 风险测评：已评测 → 结果页（等级 + 呈现文案 + 有效期 + 重新测评）；否则 → 问卷页（16 题、保存草稿 `PUT`、提交 `POST`）
- [x] 产品筛选：筛选条件（类型/风险等级/期限/起投/业绩基准）→ 符合清单（**明确写出「不是推荐」**）→ 产品详情 → 提交方案请求 → 请求列表
- [x] 我的资产：资产概览 + **实际配置 donut** + **持仓风险等级分布 bar**（两图经 `ChartFrame` + 既有 `toDonutOption` / `toBarOption`）+ 持仓明细 + 持仓穿透展开 + 交易流水筛选
- [x] 涨跌数字按红涨绿跌着色，颜色只出自 `--wm-color-up/down`，应用侧按符号挂类、不传色值
- [x] 权限与隔离：customer 的 token 不出现在 internal 的请求里（两个 localStorage key 与两个 http client 实例互不相干）
- [x] 测试（只覆盖合规呈现面与权限门控）：引用角标可点可定位；SSE 帧解析（`done` / `delta` / 异常走 `onError`）；路由守卫（未登录重定向、深链、后退键）；登出清 store；适当性说明在产品筛选页存在
- [x] `pnpm --filter @wealth/customer typecheck` 与 `test` 全绿

## 实现记录

- **适当性说明的来源与代价**：可购范围（`C4 → R1–R4`）只有 `GET /api/customer/candidate-pool` 一个来源；该接口在服务端会顺带落一条
  `SuitabilityDecision`，因此每次进入产品筛选页都会留痕。前端自行由 Cn 推 Rn 就是把适当性交给界面裁量（ADR-0005 的反面），
  所以接受这个副作用，并在 `products/api.ts` 就地记录。
- **401 中途失效补了半程**：守卫只管导航。任一接口回 401 清掉令牌后，`App.vue` 观察登录态把人送回 `/login`，
  免得客户停在一个必然报错的页面上。
- **提交方案请求后重新拉列表**（而不是本地插入新请求）：服务端才是列表的事实源，本地合并会与页面初次加载的响应抢写同一份状态。
- **测试环境的一处已知限制**：vitest 默认把 `element-plus` 外部化交给 Node 加载，而 Node 对 `async-validator`
  （CJS，只写 `exports.default`）的默认导入拿到的是对象而非构造函数，`ElForm.validate()` 因此在测试里静默放行。
  浏览器与构建产物走 Vite 的 `module` 字段（`dist-web` 的 ESM 默认导出），校验正常。登录页测试因此断言结构契约
  （每个 `el-form-item` 都在带 `rules` 的 `el-form` 之内）与失败提示面，不断言「空表单不调接口」；要覆盖那条路径
  需要把 `element-plus` 内联进测试模块图（`vite.config.ts` 的测试段，本 slice 按纪律未动）。


## 落地要点

- 只换骨架与视觉，**不改产品筛选页的字段与流程**。模块名维持「产品筛选」——「产品筛选」是 `CONTEXT.md` 的规范用词（陈述「符合条件的产品有哪些」，不评价适配性），改名会漂移语义。
- **主区限宽已取消（commit `a3c4467`）**：清单第 4 条的「主区挂 `--wm-content-max-width` 居中」在后续「宽表去掉水平滑动条」一轮被推翻。三张宽表（文档列表 / 预警列表 / 交易流水）的固有最小宽度都超过 1080px 主区实际能给出的宽度，限宽等于把水平滑动条钉在页面上——侧栏收起、展开都一样。现在 customer 主区宽度直接由网格列给出、不设上限，与 internal 主区一致；`--wm-content-max-width` 已从 `packages/shared/src/theme/tokens.css` 删除。`spec.md` 的「布局常量」与「骨架」两节、`collapsible-sidebars/issues/02-customer-app.md` 落地要点里「限宽居中、折叠只让主区可用宽度变大」的说法随之失效，以本节为准。
- 删掉旧的 `health/HealthPage.vue` 与 `api/health.ts`（上一轮的孤立页面，未挂路由）。`/api/health` 不在本 slice 的页面范围内。
- 登录页别再重复上一轮的坑（`el-form-item` 套在没有 `el-form` 的外层）。
- 聊天页的气泡与引用角标是客服链路的合规呈现面，改动时对照测试，不许为了风格牺牲可点性。
- `apps/customer/src/advisory/` 的 `submitAdvisoryRequest` / `listAdvisoryRequests` 保留（产品筛选页要用）。**`GET /api/customer/advisory/plan` 不要调用**——Q17 已决定不新增「我的方案」页，本 slice 后该接口仍无前端消费方。这是记录在案的缺口，不是遗漏；要补它需另开 spec（先回答「客户在什么场景下看、看完留不留痕」）。

## 已知取舍

- 四页放进 248px 侧栏偏空，但换来两端单一壳组件与视觉血缘；页面增多时这是正确方向的积累。
- 不做移动端适配，只有一条 <1280px 的侧栏收窄规则——客户应用的窄屏体验本 slice 不承诺。
- 客户看不到顾问定稿（Q17）：「投顾内容必须经审核后才能送达客户」这条核心约束在界面上无从体现，本 slice 的演示只能演示到「提交方案请求」。这是明确接受的代价。
