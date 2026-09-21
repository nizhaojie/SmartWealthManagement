# 01 — 待办计数的 store 与取数

**What to build:** 内部工作台第一次有了一份跨页共享的「还有几件在等顾问」。新增一个 store：取 `GET /api/internal/advisory/queue`，算出**待审内容条数**，登录 / 登出清空。`AdvisoryWorkspace` 现在自己用列表长度现算的那两个 computed 改为读它。

「同源」指的是这一条，不是「两处碰巧相等」。页面的卡片标题与角标是两个消费点，计数只在一个地方算。

**Blocked by:** 无（队列接口与角色门均已就绪，`backend/app/api/advisory.py:68-73`）

**Status:** implemented

- [x] 新增 store（`apps/internal/src/advisory/` 下，形状照 `apps/customer/src/stores/advice.ts`）：`refresh()` 拉 `getQueue()`；`pendingReviewCount` = `pending_reviews.length`；`pendingRequestCount` 一并保留（页面仍要显示「待生成的方案请求」那张卡）
- [x] 计数口径 = 队列接口给的 `pending_reviews`，因此**含「待审」与「处理中」两个状态**（`backend/app/advisory/queue.py:35` 的 `_PENDING_STATUSES`）——不要在前端按 status 过滤
- [x] 拉取失败：`failed` 置真、计数保持 `undefined`，**不是** `0`（`0` 是一句断言「没有待办」，失败时我们并不知道）
- [x] 登录 / 登出时清空（照客户侧 store 的处理：角标不带着上一位员工的数字进入新会话）
- [x] `apps/internal/src/advisory/AdvisoryWorkspace.vue:37` 的两个 computed 改为读 store，不再从自己的 `queue` 现算
- [x] 组件测试：`refresh()` 后计数等于队列条数
- [x] 组件测试：接口失败时计数为 `undefined` 且 `failed` 为真
- [x] 组件测试：登出后计数清空
- [x] 改写 `apps/internal/src/advisory/AdvisoryWorkspace.spec.ts` 中与两个计数相关的用例——**语义不变，只改数据来源**

**实现落点：** 新增 `apps/internal/src/advisory/queueStore.ts`（`useAdvisoryQueueStore`）——
`refresh()` 是 `getQueue()` 唯一的调用者，两段列表（`pendingRequests` / `pendingReviews`）与两个计数都从这一份结果派生，`pendingReviewCount` / `pendingRequestCount` 的类型是 `number | undefined`；
改 `apps/internal/src/advisory/AdvisoryWorkspace.vue`（不再自己拉队列，表格与两个计数都读 store；计数没取到时标题不带数字；队列失败时两张卡写「队列暂不可用」而不是「暂无…」）、
`apps/internal/src/stores/auth.ts`（登录与登出各调一次 `reset()`）；
测试 `apps/internal/src/advisory/AdvisoryWorkspace.spec.ts`（+3 条，共 12 条）。

这一份 issue 提到的「`AdvisoryWorkspace.spec.ts` 中与两个计数相关的用例」在改写前并不存在——那份 spec 只断言过表格行与跳转，没有断言过计数。既有的 8 条因此一条断言都没动，只是数据来源换了：stub 的还是同一个队列接口，页面改从 store 读。

### 几处写下来的决定

**计数与列表来自同一次取数，页面不再有第二份队列。** 原页面的 `queue` ref 与 store 都拉一次的话，`pendingReviewCount` 立刻又有了两个版本——那正是这条需求要消灭的东西。所以页面连两段表格也一并从 store 读，`getQueue` 在全应用只剩一个调用点。

**失败时把列表清掉，而不是留着上一轮的行。** 留着它，页面会照旧渲染一批已经不新鲜的行，而这次取数恰恰没能证明它们还对；清掉之后「不知道」这件事在页面上的表现是统一的：标题没有数字、卡片写「队列暂不可用」、顶部横幅说明原因。

**「（0）」与「暂无」是同一句断言，一起改。** 失败时卡片原本会命中「列表为空」的分支打出「暂无待审核内容」——它与 `0` 出自同一个误判：把「没取到」说成「没有」。因此两张卡都先看 `failed`，再谈列表长不长。标题侧同理：计数是 `undefined` 时不写数字，而不是退化成 `0`。

**取数结果是一个三态字段，不是几个布尔。** `status` 取 `idle` / `loaded` / `failed`，计数是否有值只看它。`failed` 是它的派生读法（页面与测试用得到），不另存一份状态——两张记号表迟早会各说各话。

**登录也清空，不只在登出时清。** 换一位员工登录时，上一位的数字还挂在角标上是最难解释的一种脏——`apps/customer/src/stores/advice.ts` 的 `reset()` 同样在两头都调。

**没有加 `loading`。** 客户侧那份 store 有它，是因为那边还有依赖加载态的渲染；这里页面还没有用到，先不加一个没人读的字段。
