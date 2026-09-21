# 09 — 内部侧的发起入口与合并的审核队列

**What to build:** 客户经理在既有 `customer-relations` 模块里为客户发起建议（那是他唯一的地盘，符合「角色可见性留在应用内」的既有做法）；顾问侧**不新开模块**——把操作建议并入既有审核队列并标注内容类型，因为审核是同一类工作，分两个队列只会让顾问漏看一半。

**Blocked by:** 08 — 客户侧的「交易」页与「我的建议」页

**Status:** implemented

- [x] `customer-relations` 模块内为客户增加「发起建议」入口与已发起建议的进度
- [x] 客户经理视角：建议只读 + 可留言，**没有放行 / 驳回入口**
- [x] 审核队列合并两类内容，每条带类型标注；等待时长仍按既有口径
- [x] 审核页按内容类型渲染不同的载荷：方案显示候选池与配置建议，操作建议只显示「一个产品、一个方向、一个金额、一条理由」
- [x] 审核页在已决定状态下仍退化为只读（沿用 `advisory-plan-visibility` 的做法）
- [x] 预警详情页增加来源标注（客户发起 / 内部补录）
- [x] 断言：客户经理视角下不存在放行 / 驳回入口
- [x] 断言：审核队列同时渲染两类内容且各带类型标注
- [x] 断言：操作建议的审核页不渲染方案特有的字段（边界没破）

**实现落点：** 后端新增 `backend/app/operation_advice/console.py`（审核状态序列化、按客户列进度的
`list_for_customer`）与 `backend/app/api/operation_advice.py` 的四个读取端点
（`GET /api/internal/operation-advice/{id}`、`/review`、`/comments` 与
`GET /api/internal/customers/{id}/operation-advice`），复用既有的
`app.advisory.access.ensure_can_view`、`app.advisory.comments`、`app.advisory.review.get_review_by_content`；
`backend/app/operation_advice/decision.py` 把 `released_at_by_review` / `decisions_by_advice` /
`product_names` 三处查询公开（内部侧进度与客户侧读取读同一份事实）；
测试 `backend/tests/test_operation_advice_console.py`（新增，9 条）。

前端新增 `apps/internal/src/operation-advice/`（`api.ts`、`types.ts`、`view.ts`、
`AdvicePayloadPanel.vue`、`AdviceReviewPage.vue`、`CustomerAdviceSection.vue`）；
改既有：`advisory/AdvisoryWorkspace.vue`（待审队列与历史各加类型列、摘要按类型给、按类型跳转）、
`advisory/reviewView.ts`（`reviewTarget` / `reviewSummaryLabel`）、`advisory/types.ts`
（`ContentType` 与唯一的审核状态集 `ReviewStatus`）、`router/index.ts`
（`advisory/operation-advice/:adviceId`）、`customer-relations/CustomerRelationsPage.vue`（挂发起入口）、
`risk/types.ts` 与 `risk/AlertDetailPage.vue`（来源标注）、`risk/riskView.ts`
（`alertSourceTagType` / `alertSourceNote`）；测试
`operation-advice/AdviceReviewPage.spec.ts`（8 条）、`operation-advice/CustomerAdviceSection.spec.ts`（8 条），
并扩了 `advisory/AdvisoryWorkspace.spec.ts`（队列两类内容，5 条）、`risk/AlertDetailPage.spec.ts`（来源，2 条）、
`risk/riskView.spec.ts`（来源标注，2 条）。

### 几处写下来的决定

**两类内容共用审核的那一半，不共用载荷的那一半。** 审核决定面板、留言面板、403 与「已决定即只读」
这三条规则在两张审核页上完全一致，因此共用同一批组件与 `canReview` / `isDecided`；**载荷渲染件
共用不了**——把方案的渲染件拿过来，只会在建议上渲染出一堆空字段，而那种页面看起来仍然「正常」。
这张边界靠测试钉住：给建议塞进 `candidates` / `allocation_suggestion` / `warnings` 并断言它们不出现。

**跳哪一张审核页由内容类型决定，判断只写一处。** `reviewTarget(contentType, contentRef)` 是唯一的
跳转口径，模板里不写 if——写错一个分支的后果是跳到一张渲染空字段的页面上，两处都看起来正常。

**进度是两个口径、两列，不合成一个字段。** 审核进度说「顾问看了没有」，客户决定说「客户答了没有」；
未放行时客户决定是**空**而不是「待客户决定」，因为客户此刻根本读不到这条建议。合成一处会丢掉
其中一半，而丢掉的那一半正是客户经理此刻要的答案。

**可见范围按客户归属判定，不按发起人。** 客户经理看得到名下客户身上的全部建议，包括上一任经理
发起的那条（按发起人过滤会让他在接手后看到一个不像真的账户）；理财顾问不受限。这一条与审核队列、
预警列表同一个口径，落在 `ensure_can_view`。

**来源标注只给「内部补录」加一句补充说明。** 「客户发起的交易是客户发起的」不必解释；内部补录
反直觉——它没过适当性与余额校验（Q22），所以说一句。补充说明与标签色都由 `riskView` 一处给出，
详情页不自己比字符串。

**后端不新增写入路径。** 这一份只有读取：放行 / 驳回仍是 #07 落的
`POST /api/internal/operation-advice/{id}/release|reject`，留言仍按审核记录寻址
（`app.advisory.comments`，与内容类型无关）。审核状态与进度的「已放行时间」都取自既有的
审核记录与放行留痕，没有第二份口径。
