# 顾问的待审核提醒

Status: ready-for-agent

前置：`advisory-agent-and-review-flow`（审核队列与放行驳回）、`operation-advice-and-customer-trading` 的 `#09`（两类内容合并进同一条队列）、`frontend-rebuild`（壳与导航 badge 能力）

本 slice **不修改**任何已实现的既有决定，也不新增后端接口。

## Problem Statement

**待审核的内容不会被它的处置人看见。**

审核队列是有的。`GET /api/internal/advisory/queue`（`backend/app/api/advisory.py:68`）把「待生成的客户方案请求」与「待审核的投顾内容」两段一起返回，后者已按 ADR-0020 合并了方案与操作建议（`backend/app/advisory/queue.py:72`）。但这个接口只在一个地方被消费：顾问自己走进 `/advisory` 模块、页面挂载、列表拉回来之后（`apps/internal/src/advisory/AdvisoryWorkspace.vue:118`）。在那之前，队列对他不存在。

数字也只活在那一页里：`AdvisoryWorkspace.vue:37` 用列表长度现算，渲染在页内卡片标题上（`:189`）。切到知识库、数据分析、客户画像或客户关系，这件事就消失了。

而队列是被三条路径持续写入的：客户提交方案请求、顾问生成方案后在 `interrupt` 处中断（`backend/app/advisory/graph.py:195`）、客户经理发起操作建议后在 `interrupt` 处中断（`backend/app/operation_advice/graph.py:230`）。写入者不出现，读取者也不被叫。

后端没有任何提醒能力，这一点是查证过的而不是推断的：无 WebSocket；SSE 只有客户聊天的逐字推流（`backend/app/api/chat.py:98`）；进程内周期任务只有画像置信度校准（`backend/app/scheduler.py:34`）；事件总线是 Agent 之间的协作记录（`backend/app/event_subscribers.py:85`），不面向任何人。前端对审核队列也没有轮询。

对照之下，客户侧已经有对称的能力：「我的建议」页有「待客户决定」的角标，数据来自一个 store（`apps/customer/src/stores/advice.ts:36`），由壳渲染（`packages/shared/src/shell/AppShell.vue:42`、`apps/customer/src/shell/CustomerShell.vue:28`）。壳本来就支持 `navItems[].badge`，缺的这一侧是顾问。

## Solution

**给顾问的「投顾助手」导航项加一个待办计数**（`CONTEXT.md` 新增词条：待办计数）。

- **形态**：导航项角标。与客户侧「我的建议」用的是同一套机制，不新造展示语言。投顾助手模块本身只对理财顾问可见（`apps/internal/src/shell/modules.ts:58`），因此角色隔离天然成立，不需要额外判断。
- **口径**：等于**待审内容的条数**，含「待审」与「处理中」两个状态（`backend/app/advisory/queue.py:35` 的 `_PENDING_STATUSES`）。不含「待生成的方案请求」——「审核」在 `CONTEXT.md` 里是有精确定义的（放行或驳回判定），把「等顾问生成」并进同一个数字会让这个词在界面上失去含义。
- **来源**：复用 `GET /api/internal/advisory/queue`，不新增 count 接口。角标与页面列表因此**天然同源**——角标说 3、点进去是 2，正是提醒失效的形态，而两个接口的口径迟早会漂移。
- **时效**：进壳时拉一次；顾问在审核页放行 / 驳回 / 生成成功后刷新同一个 store。不加轮询、不加 SSE。代价明确：工作台开着不动时新内容不会自己冒出来，要切页或刷新。
- **降级**：拉取失败时不渲染角标。不渲染 `0`——`0` 是一句断言（「没有待办」），而失败时我们并不知道。

## 访谈结论清单（grill-with-docs，2026-09-21）

这一天的访谈同时产出另一份 spec（`operation-advice-product-choice`），编号是共用的；本表只记属于本 slice 的部分。

### 第一轮

| # | 决定 |
|---|---|
| Q1 | 提醒的形态 = **导航项角标**，不做侧栏底部计数卡片、不做桌面通知或站内信。 |
| Q2 | 口径 = **只数待审内容**，不含待生成的方案请求。 |
| Q3 | 角色范围 = **只做理财顾问**；客户经理侧与风控专员侧的对称提醒登记为后续。 |

### 第二轮

| # | 决定 |
|---|---|
| Q6 | 数字**复用既有队列接口**，壳挂载时拉一次，审核动作完成后刷新同一个 store；**不加轮询、不加 SSE**。 |
| Q7 | 「处理中」**计入**待办计数——角标必须等于点进去看到的条数。 |

### 第三轮

| # | 决定 |
|---|---|
| Q14 | slug 定为 `advisor-review-reminder`。 |

## User Stories

### 理财顾问

1. As a 理财顾问, I want to 在工作台的任意页面看到还有多少内容在等我审核, so that 我不必先回到投顾助手模块才知道
2. As a 理财顾问, I want to 这个数字与点进去看到的条数一致, so that 我不会开始怀疑它
3. As a 理财顾问, I want to 放行或驳回之后数字立刻减少, so that 我知道刚才那一下生效了
4. As a 理财顾问, I want to 没有待审内容时不显示角标, so that 界面不制造虚假的紧迫感

### 其他角色

5. As a 客户经理, I want to 看不到审核待办角标, so that 我不会被一个我无权处置的数字催促
6. As a 风控专员, I want to 看不到审核待办角标, so that 我的工作台不出现别人的待办

### 开发者

7. As a 开发者, I want to 角标数与队列页的数字来自同一处, so that 两处不会各算各的
8. As a 开发者, I want to 队列接口不可用时角标消失而不是显示 0, so that 界面不把「不知道」说成「没有」

## Implementation Decisions

### 计数只在一处算

internal 应用新增一个 store（照 `apps/customer/src/stores/advice.ts` 的样子：拉取、存列表、算计数），壳的角标与审核页的卡片标题都读它。`AdvisoryWorkspace.vue:37` 现在自己用列表长度现算的那两个 computed 改为读 store——这才是「同源」的实现，而不是两处碰巧相等。

登录 / 登出时清空，与客户侧同一处理（`stores/advice.ts` 的做法）：角标不该带着上一位员工的数字进入新会话。

### 刷新时机

- 壳挂载时拉一次（`WorkbenchShell.vue` 是唯一的挂载点）。
- 审核动作成功后刷新：方案侧的放行 / 驳回（`AdvisoryReviewPage.vue`）与操作建议侧的同两个动作（`AdviceReviewPage.vue`），以及方案生成成功后（`AdvisoryWorkspace.vue` 的生成入口）——生成会立刻产生一条待审内容。
- 不做轮询。仓库里唯一的轮询先例（`apps/internal/src/knowledge/DocumentManagerPanel.vue:68`，1.5s）等的是几十秒内结束的短任务；审核待办是小时级变化。

### 失败与空态

- 队列接口失败：不渲染角标（`navItems[].badge` 为 `undefined`），不渲染 `0`，也不在壳里显示错误——壳没有地方放错误文案，而角标本身是可以缺席的。
- 计数为 0：不渲染角标（`AppShell.vue:42` 的 `v-if="item.badge"` 已经这么做了，不要改成恒显）。

### 不改的东西

- 不加后端接口，不加数据库表，不加通知 / 未读 / 回执概念。
- 不改审核队列的返回结构、排序与角色门（`api/advisory.py:70` 的 `require_employee_role(ADVISOR)`）。
- 不改侧栏底部的「今日风险预警」卡片（`shell/RiskAlertSummaryCard.vue`）——它属于风控，与审核无关。

## Testing Decisions

**这条需求没有后端改动，因此只有一个 seam。**

### Seam 2 — Vue 组件挂载

- 待审内容非空时，「投顾助手」导航项渲染角标，值等于队列条数
- 计数为 0 时不渲染角标
- 队列接口失败时不渲染角标（**不渲染 0**）
- 放行成功后角标减一；驳回成功后角标减一
- 队列为空时角标消失
- 客户经理登录后的导航里不存在投顾助手项（既有断言的延续），因此也不存在角标
- 角标与审核页卡片标题的数字来自同一个 store：断言两处不各自维护一份计数（例如只 stub 一次接口，两个位置必须同时反映它）

### 要复用的既有断言

- `apps/internal/src/advisory/AdvisoryWorkspace.spec.ts`——卡片标题里的计数已有断言，改动数据来源后要重跑
- 角色可见性已有断言（模块级），本 slice 不新增角色判断

## Out of Scope

- **推送式通知渠道**（站内信、短信、邮件）——沿袭 `advisory-agent-and-review-flow` 与 `advisory-plan-visibility` 的排除
- 浏览器桌面通知与声音提示
- 轮询与 SSE 推送
- 客户经理侧（「我发起的建议在等审核 / 客户已决定」）与风控专员侧的对称提醒
- 待生成方案请求的提醒（它不该并入审核数字；要不要单独提醒本 slice 不回答）
- 角标的 SLA、超时升级与未处理堆积的二次提醒

## Further Notes

- **「提醒」在这套系统里是界面读数，不是通知能力。** 实现时若出现一张 notification 表、一条 SSE 通道、一个未读标记或一条回执，方向就错了。`CONTEXT.md` 新增的「待办计数」与既有的「送达」两条词条合起来说明这件事：送达由放行一次性决定、不产生回执；这里加的是「还有几件在等」的读数，不是「已经告诉过谁」。
- **「数字为零不渲染角标」与风险卡片「N=0 给一句空态文案」有意不同。** 卡片有位置可以写一句话，角标没有；显示「0」比不显示更像出了错。
- **只在自己刷新时才对，是刻意认下的代价。** 若答辩或演示需要「新内容自己冒出来」，那是一次显式的口径变更（加轮询），不是顺手补一行 `setInterval`——顺便说，把轮询间隔抄成 1.5s 只会让评委看见一个每 1.5 秒就敲一次后端的演示。
- 这一条与 `frontend-rebuild` 的 `AppShell` 契约不冲突：壳只认 `badge?: number` 这个数字，「投顾助手」是什么、待审是什么，壳不知道也不该知道。
