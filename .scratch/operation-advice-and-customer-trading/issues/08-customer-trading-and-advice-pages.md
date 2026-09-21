# 08 — 客户侧的「交易」页与「我的建议」页

**What to build:** 客户侧第一次有了写操作页面。新增两个页面而不是一个：「交易」是客户主动做的事，「我的建议」是等他做决定的事（收件箱，带角标）；「我的方案」保持只读回看（资料库）。把建议塞进只读页面，客户不会发现有待他决定的东西。

**Blocked by:** 07 — 客户的最终决定权

**Status:** implemented

- [x] 「交易」页：可用余额 + 申购 / 赎回 / 转账三个入口；落在 `apps/customer/src/` 的独立域内，不新建 `views/`
- [x] **交易页必须独立**，不长在只读的资产页里——它是客户侧第一个写操作页面
- [x] 「我的建议」页：待决定 / 已接受 / 已拒绝 / 已过期四种状态；有待决定项时侧栏出现角标
- [x] 资产页增加可用余额的展示与「去交易」入口；流水列表改为渲染三类记录（转账行显示收款人）
- [x] 失败文案各自可辨：余额不足 / 产品越级 / **未测评**（这条要能点到风险测评页）/ 已过期
- [x] 接受失败时渲染原因，且该条建议仍在待决定区
- [x] 空状态：无建议、无交易、无持仓三种情形都不留空白
- [x] 侧栏新增两项，`key` 与 path 同名（沿用既有约定）
- [x] 断言：三类失败各自渲染对应文案；未测评的那条能跳到测评页
- [x] 断言：有待决定建议时角标出现；接受失败后该条仍在待决定区

**实现落点：** 新增 `apps/customer/src/funding/`（`api.ts`、`types.ts`、`useAvailableBalance.ts`，
可用余额只读 + 两页共用的加载口径）、
`apps/customer/src/trading/`（`api.ts`、`types.ts`、`failure.ts`、`FailureNotice.vue`、`TradingPage.vue`）、
`apps/customer/src/operation-advice/`（`api.ts`、`types.ts`、`AdvicePage.vue`）、
`apps/customer/src/stores/advice.ts`（建议列表 + 待决定角标数）；改
`apps/customer/src/router/index.ts`（`/trading`、`/operation-advice`）、
`apps/customer/src/shell/CustomerShell.vue`（新增两项导航 + 角标）、
`apps/customer/src/assets/AssetsPage.vue`（可用余额 +「去交易」）、
`apps/customer/src/assets/TransactionHistory.vue` 与 `assets/types.ts`（三类记录 + 收款人列、可空字段）、
`apps/customer/src/stores/auth.ts`（登录 / 登出清角标）；测试
`trading/TradingPage.spec.ts`（8 条）、`operation-advice/AdvicePage.spec.ts`（8 条）、
`assets/AssetsPage.spec.ts`（3 条），并更新 `App.spec.ts`（导航七项 + 角标）。

### 几处写下来的决定

**失败只有一种呈现，且「未测评」按文案相等判定。** 交易页的三个入口与「我的建议」的接受
拿到的都是受理侧的原文，因此共用 `trading/FailureNotice.vue` 一处渲染。其中只有「未测评」
这一条是客户自己能解决的，要顺带给出测评入口；它和越级都是 403，光看状态码分不开，只能按
文案相等（`describeAcceptanceFailure` 里的 `ASSESSMENT_REQUIRED_MESSAGE`）判。代价写在那里：
服务端改这句话，前端只是不再给出入口，不会报错。

**「拉取失败」不写成「你没有」。** 余额、持仓与在售产品各自有独立的失败分支：拉不到就说
拉不到，不置成零、也不说成「没有可赎回的持仓」——后者会让客户去查一个并不存在的问题。
空状态只在**成功读到空**时出现，三条（无建议 / 无交易 / 无持仓）之外，交易页的申购区在
成功读到空产品时也给一句说明，免得下拉是空的而页面看起来像坏了。

**建议的免责声明照常渲染。** `disclaimer` 是客户送达视图里十二个字段之一（#07），字段送到
了界面就不该丢——不渲染它等于把服务端做过的裁剪又原样取消了一半。

**可用余额自成一个 `funding` 域。** 资产页与交易页都读它，谁都不去对方的域里取——
放进 `assets/api` 会让交易页依赖资产页，放进 `trading/api` 会让资产页依赖交易页，两条都是
「为了少一个文件」而把两个页面绑在一起。

**接受失败不刷新列表。** 受理校验没过时建议仍留在待客户决定（#07），刷新反而会把一条什么
都没发生的建议说成别的状态；原因就地渲染在那一条上。成功才刷新——状态由服务端现算，前端
不推导「已过期」。

**角标与页面共用一个 store。** 页面按状态分组渲染、壳只数「待客户决定」的条数，两份数据
分开拿的话，客户接受之后角标要等下一次谁去刷新才掉。这份 store 在登录 / 登出时与对话一起
清空：角标不该带着上一位客户的数字进入新会话。

**空状态各有一处。** 无建议 → 「我的建议」的空状态（并给「去交易」的出口）；无交易 →
既有的流水空提示；无持仓 → 交易页赎回区的空状态（表单整块换成一句说明），不留一个空的下拉。
