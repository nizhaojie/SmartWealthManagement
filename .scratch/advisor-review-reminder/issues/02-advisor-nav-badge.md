# 02 — 顾问导航项的待办角标

**What to build:** 把 01 的计数钉到「投顾助手」导航项上，顾问在知识库、数据分析、客户画像、客户关系、风控监测任意一页都能看见还有多少内容在等他审核；做完放行 / 驳回 / 生成之后数字立刻跟着变。

形态用导航项角标而不是侧栏底部计数卡片：客户侧「我的建议」的「待客户决定」已经在用同一套机制（`packages/shared/src/shell/AppShell.vue:42`、`apps/customer/src/stores/advice.ts:36`），顾问侧对称过来不必新造展示语言；而投顾助手模块本身只对理财顾问可见（`apps/internal/src/shell/modules.ts:58`），角色隔离天然成立，不需要额外判断。

**Blocked by:** 01 — 待办计数的 store 与取数

**Status:** ready-for-agent

- [ ] `apps/internal/src/shell/WorkbenchShell.vue:18` 的 `navItems` 为 `advisory` 一项带上 `badge`（`AppShellNavItem` 已支持该字段）
- [ ] 壳挂载时刷新一次 store
- [ ] 审核动作成功后刷新 store：`advisory/AdvisoryReviewPage.vue` 的放行 / 驳回、`operation-advice/AdviceReviewPage.vue` 的放行 / 驳回、`advisory/AdvisoryWorkspace.vue` 的生成入口（生成会立刻产生一条待审内容）
- [ ] 计数为 `0` 或拉取失败时**不渲染**角标（`AppShell.vue:42` 的 `v-if="item.badge"` 已同时覆盖 `undefined` 与 `0`，不要改成恒显）
- [ ] 不新增角色判断：角标跟着模块可见性走
- [ ] **组件测试：待审内容非空时角标出现，且值等于队列条数**
- [ ] 组件测试：计数为 `0` 时不渲染角标
- [ ] **组件测试：队列接口失败时不渲染角标，且不渲染 `0`**
- [ ] 组件测试：放行成功后角标减一；驳回成功后角标减一
- [ ] 组件测试：客户经理登录后侧栏不存在投顾助手项，因而不存在角标（既有角色可见性断言的延续，本份不新增断言以外的判断）

**注意：** 不加轮询、不加 SSE。仓库里唯一的轮询先例（`apps/internal/src/knowledge/DocumentManagerPanel.vue:68`，1.5s）等的是几十秒内结束的短任务；把它的间隔抄过来，只会让评委看见一个每 1.5 秒敲一次后端的演示。代价已明确认下：工作台开着不动时新内容不会自己冒出来。
