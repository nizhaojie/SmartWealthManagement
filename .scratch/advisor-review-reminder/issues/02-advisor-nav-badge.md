# 02 — 顾问导航项的待办角标

**What to build:** 把 01 的计数钉到「投顾助手」导航项上，顾问在知识库、数据分析、客户画像、客户关系、风控监测任意一页都能看见还有多少内容在等他审核；做完放行 / 驳回 / 生成之后数字立刻跟着变。

形态用导航项角标而不是侧栏底部计数卡片：客户侧「我的建议」的「待客户决定」已经在用同一套机制（`packages/shared/src/shell/AppShell.vue:42`、`apps/customer/src/stores/advice.ts:36`），顾问侧对称过来不必新造展示语言；而投顾助手模块本身只对理财顾问可见（`apps/internal/src/shell/modules.ts:58`），角色隔离天然成立，不需要额外判断。

**Blocked by:** 01 — 待办计数的 store 与取数

**Status:** implemented

- [x] `apps/internal/src/shell/WorkbenchShell.vue:18` 的 `navItems` 为 `advisory` 一项带上 `badge`（`AppShellNavItem` 已支持该字段）
- [x] 壳挂载时刷新一次 store
- [x] 审核动作成功后刷新 store：`advisory/AdvisoryReviewPage.vue` 的放行 / 驳回、`operation-advice/AdviceReviewPage.vue` 的放行 / 驳回、`advisory/AdvisoryWorkspace.vue` 的生成入口（生成会立刻产生一条待审内容）
- [x] 计数为 `0` 或拉取失败时**不渲染**角标（`AppShell.vue:42` 的 `v-if="item.badge"` 已同时覆盖 `undefined` 与 `0`，不要改成恒显）
- [x] 不新增角色判断：角标跟着模块可见性走
- [x] **组件测试：待审内容非空时角标出现，且值等于队列条数**
- [x] 组件测试：计数为 `0` 时不渲染角标
- [x] **组件测试：队列接口失败时不渲染角标，且不渲染 `0`**
- [x] 组件测试：放行成功后角标减一；驳回成功后角标减一
- [x] 组件测试：客户经理登录后侧栏不存在投顾助手项，因而不存在角标（既有角色可见性断言的延续，本份不新增断言以外的判断）

**实现落点：** 改 `apps/internal/src/shell/WorkbenchShell.vue`（`navItems` 的 `badge` 只给 `advisory` 一项、`onMounted` 拉一次 store）、
`apps/internal/src/advisory/AdvisoryReviewPage.vue` 与 `apps/internal/src/operation-advice/AdviceReviewPage.vue`（放行 / 驳回成功后 `await queue.refresh()`，失败路径不刷）、
`apps/internal/src/advisory/AdvisoryWorkspace.vue`（两个生成入口成功后刷新）；
新增 `apps/internal/src/shell/advisoryQueueBadge.spec.ts`（7 条）。

### 几处写下来的决定

**刷新放在动作成功之后，不放在 `finally` 里。** 失败时那条内容还在待审队列里，角标不该动；`queue.refresh()` 自身不抛（失败记在 store 的 `status` 上），因此放在 `try` 里不会把动作改成「刷新失败即动作失败」。

**壳挂载时无条件拉一次，不按角色门控。** 角标跟着模块可见性走指的是「渲染」，不是「取数」：客户经理登录后队列接口本来就会 403，那次取数落在 store 的失败态上，而他没有投顾助手这一项，两次都不会画出角标。多加一条角色判断反而会造出第二份「谁能看见什么」。

**同源被断言成一次挂载里的两处读数。** `advisoryQueueBadge.spec.ts` 只 stub 一次队列接口，导航角标与审核页卡片标题在同一个壳里必须同时反映它——分开断言两处各自等于 2 的话，两份计数各自维护也照样通过。

**测试里补了客户画像与资产的 stub。** 审核页会把「当前客户」钉给检查器，检查器随后拉 `/customers/:id/profile` 与 `/assets`；`testing.ts` 的默认值以 `/api/internal/customers` 为前缀，会把这两条也答成空数组，数组是「取到了」，画像渲染随即打穿（先前没有整壳挂载 + 选中客户的用法，因此这一条是新暴露的测试替身缺口，不是产品缺陷）。

**注意：** 不加轮询、不加 SSE。仓库里唯一的轮询先例（`apps/internal/src/knowledge/DocumentManagerPanel.vue:68`，1.5s）等的是几十秒内结束的短任务；把它的间隔抄过来，只会让评委看见一个每 1.5 秒敲一次后端的演示。代价已明确认下：工作台开着不动时新内容不会自己冒出来。
