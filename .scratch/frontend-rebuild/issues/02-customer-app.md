# 02 — customer 应用重写（两栏骨架 + 登录页 + 四页）

**What to build:** 删掉 `apps/customer/src` 全部内容与全部 `*.spec.ts`，在 01 的 shared 地基上重写客户应用：两栏骨架（侧栏 + 主区限宽居中，无右侧检查器）、02 语言的登录页、以及智能对话 / 风险测评 / 产品筛选 / 我的资产四页。工程装配（`package.json`、`vite.config.ts` 的 5173 端口与 `/api` 代理、`tsconfig.json`、`index.html`）不动。

客户侧是**客户可见视图**边界之内的一切：持仓、交易流水、风险测评结论、事实性内容。画像与服务记录在其之外，本应用不得请求。

**Blocked by:** 01 — shared 地基

**Status:** todo

- [ ] 登录页（02 语言，整屏两栏：左品牌区 + 右登录卡；纯 CSS 无图片资源）：**正确使用 `el-form` + `rules`**，失败给内联提示而非 toast；品牌文案「智能财富管家」
- [ ] 登录成功写入 `auth` store 的 tokens（沿用既有 localStorage key 语义），登出调 `POST /api/customer/auth/logout` 并清 store
- [ ] 路由：`/login`（public）、`/chat`、`/risk-assessment`、`/products`、`/assets`；非 public 且未登录 → `/login`，已登录访问 public → `/chat`
- [ ] 外壳：`AppShell` 不提供 `inspector` 插槽，主区挂 `--wm-content-max-width` 居中；导航 4 项（智能对话 / 风险测评 / 产品筛选 / 我的资产）配 EP 图标
- [ ] 智能对话页：`POST /api/customer/chat/stream` 的 SSE 流式增量渲染（`fetch` + `body.getReader()` 按 `\n\n` 切帧，不用 `EventSource`；`event: done` 携带答案与引用、其余帧携带 `delta`）
- [ ] **引用角标**：回答中的 `[n]` 渲染为可点击角标，点击后展示 `title` / `source_file` / `heading_path`；检索不到依据时的兜底话术与人工热线原样保留
- [ ] 会话消息放在 `chat` store，**不跨登录延续**（重新登录即新会话）；滚动与 composer 交互对齐 02
- [ ] 风险测评：已评测 → 结果页（等级 + 呈现文案 + 有效期 + 重新测评）；否则 → 问卷页（16 题、保存草稿 `PUT`、提交 `POST`）
- [ ] 产品筛选：筛选条件（类型/风险等级/期限/起投/业绩基准）→ 符合清单（**明确写出「不是推荐」**）→ 产品详情 → 提交方案请求 → 请求列表
- [ ] 我的资产：资产概览 + **实际配置 donut** + **持仓风险等级分布 bar**（两图经 `ChartFrame` + 既有 `toDonutOption` / `toBarOption`）+ 持仓明细 + 持仓穿透展开 + 交易流水筛选
- [ ] 涨跌数字按红涨绿跌着色，颜色只出自 `--wm-color-up/down`，应用侧按符号挂类、不传色值
- [ ] 权限与隔离：customer 的 token 不出现在 internal 的请求里（两个 localStorage key 与两个 http client 实例互不相干）
- [ ] 测试（只覆盖合规呈现面与权限门控）：引用角标可点可定位；SSE 帧解析（`done` / `delta` / 异常走 `onError`）；路由守卫（未登录重定向、深链、后退键）；登出清 store；适当性说明在产品筛选页存在
- [ ] `pnpm --filter @wealth/customer typecheck` 与 `test` 全绿

## 落地要点

- 只换骨架与视觉，**不改产品筛选页的字段与流程**。模块名维持「产品筛选」——「产品筛选」是 `CONTEXT.md` 的规范用词（陈述「符合条件的产品有哪些」，不评价适配性），改名会漂移语义。
- 删掉旧的 `health/HealthPage.vue` 与 `api/health.ts`（上一轮的孤立页面，未挂路由）。`/api/health` 不在本 slice 的页面范围内。
- 登录页别再重复上一轮的坑（`el-form-item` 套在没有 `el-form` 的外层）。
- 聊天页的气泡与引用角标是客服链路的合规呈现面，改动时对照测试，不许为了风格牺牲可点性。
- `apps/customer/src/advisory/` 的 `submitAdvisoryRequest` / `listAdvisoryRequests` 保留（产品筛选页要用）。**`GET /api/customer/advisory/plan` 不要调用**——Q17 已决定不新增「我的方案」页，本 slice 后该接口仍无前端消费方。这是记录在案的缺口，不是遗漏；要补它需另开 spec（先回答「客户在什么场景下看、看完留不留痕」）。

## 已知取舍

- 四页放进 248px 侧栏偏空，但换来两端单一壳组件与视觉血缘；页面增多时这是正确方向的积累。
- 不做移动端适配，只有一条 <1280px 的侧栏收窄规则——客户应用的窄屏体验本 slice 不承诺。
- 客户看不到顾问定稿（Q17）：「投顾内容必须经审核后才能送达客户」这条核心约束在界面上无从体现，本 slice 的演示只能演示到「提交方案请求」。这是明确接受的代价。
