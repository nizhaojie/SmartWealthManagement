# 投顾内容的送达面

Status: ready-for-agent

前置：`advisory-agent-and-review-flow`（顾问定稿与审核流）、`frontend-rebuild`（两端骨架已重做）

**取代**：`frontend-rebuild` 的 Q17（「客户侧不新增我的方案页」）。那份 spec 本身不修改，本 slice 是它要求「另开一份 spec」的那个后续。

## Problem Statement

投顾内容的链路在界面上断成了两截，两截都缺同一个东西：**顾问定稿被生产出来之后，没有一个地方能被它应该被看见的人看见。**

客户侧：`GET /api/customer/advisory/plan` 是**顾问定稿**唯一的出口，也是「投顾内容必须经审核后才能送达客户」这条红线的终点。但前端没有任何页面消费它（`apps/customer/src/advisory/api.ts:3-5` 记录了这一点）。客户提交「请顾问出具方案」之后，能看见请求状态从「待处理」走到「已完成」，然后就没有然后了——顾问写的东西到不了客户眼前。这条红线在界面上守护的是一扇没人走的门。

顾问侧：审核页本身是好的，`AdvisoryReviewPage` 在状态为已放行时会加载并渲染定稿（`AdvisoryReviewPage.vue:101-103`）。但「我审核过的记录」这张表只渲染审核流水——客户、操作、驳回理由、操作时间（`AdvisoryWorkspace.vue:210-222`），**没有任何行内动作**，而它的数据源 `list_my_history` 也不含内容（`backend/app/advisory/queue.py:76-95`）。顾问放行完一份方案，此后就只能看见「我放过行」这四个字。对照「待审核」表有「查看」按钮走 `openReview(row.draft_id)`（`AdvisoryWorkspace.vue:109-111`），历史表只是忘了接同一根线。

`frontend-rebuild` 的 Q17 决定不做客户侧页面，理由是它引入的是「客户如何接收投顾内容」这个新问题——送达方式、查看留痕、过期与否。本 slice 就是回答那个问题。答案是：**拉取式、无留痕、无硬过期**。

## Solution

**客户侧**：新增一级导航「我的方案」（`/advisory`），页面分两个分区——「已放行方案」与「方案请求进度」。前者来自新增的客户侧接口，返回该客户的**顾问定稿**；后者承接原本挂在产品筛选页的请求列表，产品筛选页只留「请顾问出具方案」按钮。点一份方案进入独立详情路由 `/advisory/plans/:finalId`。

客户看到的不是定稿的全部内容，而是定稿中**客户可见视图**以内的部分，即**客户送达视图**：产品要素、配置建议、出具顾问、放行时间、免责声明。**推荐理由不在其中**——它的措辞是顾问举证的口气（「客户风险承受等级为 C3…」，人称是「客户」不是「您」），并且引用了画像标签（「符合画像记录的产品偏好」「客户投资经验为『…』」），而画像在客户可见视图之外。这层裁剪由**服务端的独立序列化函数**承担，不是前端的展示习惯：什么能送达客户是合规规则，放在前端一改就破。

**顾问侧**：「我审核过的记录」每行加一个「查看」动作，跳到已有的审核页；该页在已决定状态下退化为只读。

## 访谈结论清单（grill-with-docs，2026-09-19，三轮共 14 问）

### 第一轮

| # | 决定 |
|---|---|
| Q1 | 交付物是**拉取式页面**，不是推送通知。`advisory-agent-and-review-flow` 对通知渠道（站内、短信、邮件）的排除保持不变。 |
| Q2 | 客户侧用**独立序列化函数**，裁剪在服务端；**综合得分不显示给客户**。 |
| Q3 | 客户可看**多份定稿**：新增列表接口与按 id 查详情；现有 `/plan`（最新一份）保留不动。 |
| Q4 | **不留痕**：不记「已送达 / 已读」，不加确认动作。 |

### 第二轮

| # | 决定 |
|---|---|
| Q5 | 入口是**新增一级导航「我的方案」**；产品筛选页的「我的方案请求」列表迁入该页。 |
| Q6 | 尚无已放行方案时，空状态位置**直接渲染方案请求进度**，不留一块空白。 |
| Q7 | **不设硬过期**；只显示「出具于 X（N 天前）」并附一句「本方案基于出具时点的画像与市场数据」。 |
| Q8 | 顾问侧历史表加「查看」动作，跳现有审核页；该页在已决定状态下改为只读形态。 |
| Q9 | 顾问可看范围**维持不变**（只看自己审核过的），不扩权。 |
| Q10 | `CONTEXT.md` 改**客户可见视图**、新增**送达**与**客户送达视图**；新增一条 ADR。 |

### 第三轮

| # | 决定 |
|---|---|
| Q11 | 列表页 `/advisory` + 独立详情路由 `/advisory/plans/:finalId`。 |
| Q12 | 裁剪清单见下；**推荐理由不进客户视图**；客户侧 `advisory-requests` 响应里的 `customer_id` 一并去掉。 |
| Q13 | 页面分**两个分区**，不合成一条时间线——直接生成的方案没有对应请求，以请求为主键会出现孤儿。 |
| Q14 | 提交请求成功后**跳转到「我的方案」页**。 |

## User Stories

### 客户

1. As a 客户, I want to 在一个固定的地方看到顾问为我出具的方案, so that 我不必反复去问顾问有没有结果
2. As a 客户, I want to 看到的是顾问放行后的版本, so that 我看到的内容经过专业人员把关
3. As a 客户, I want to 看到方案是哪位顾问出具的、什么时候出具的, so that 我知道该找谁，也知道这个结论有多新
4. As a 客户, I want to 看到方案里的产品要素与配置建议, so that 我知道顾问建议我做什么
5. As a 客户, I want to 看到免责声明, so that 我理解它的性质
6. As a 客户, I want to 回看以前收到的方案, so that 我不是只有最新一份
7. As a 客户, I want to 看到自己的方案请求走到哪一步了, so that 我知道谁在等我
8. As a 客户, I want to 还没收到方案时不看到一块空白, so that 我知道系统正常、请求在等顾问
9. As a 客户, I want to 从提交请求的地方直接走到方案页, so that 我提交完就知道该去哪里看结果
10. As a 客户, I want to 在方案详情里自由来回, so that 浏览器后退键能把我带回列表

### 理财顾问

11. As a 理财顾问, I want to 从「我审核过的记录」点进一份内容, so that 我能回看自己放行了什么、驳回了什么
12. As a 理财顾问, I want to 回看已决定的内容时看到的是只读页面, so that 我不会误以为还能再放行一次
13. As a 理财顾问, I want to 回看时仍能并排看到 AI 原稿与顾问定稿, so that 我能回忆当时改了什么

### 合规负责人

14. As a 合规负责人, I want to 未经审核的投顾内容在任何客户侧接口都读不到, so that 红线不依赖流程自觉
15. As a 合规负责人, I want to 客户侧响应里不含预警、评分与内部标识, so that 客户可见视图的边界在响应体上也成立
16. As a 合规负责人, I want to 客户只能按 id 读到自己名下的定稿, so that 新增的详情接口不成为越权的后门

### 开发者

17. As a 开发者, I want to 裁剪只发生在一个服务端函数里, so that 以后新增客户侧出口时不会各自漂移
18. As a 开发者, I want to 两端的「列表 → 详情」用同一套路由习惯, so that 我不必为一次点击发明新的导航模式

## Implementation Decisions

### 送达是放行的一个结果，不是一段过程

送达不产生任何记录：没有回执表、没有 `read_at`、没有「确认收到」。客户什么时候看到、看没看到，不改变任何状态。这条要写进词汇表，挡住后来者顺手加一列。

### 客户送达视图

服务端新增 `serialize_final_for_customer`，与内部端在用的 `serialize_final` 并存：

| 字段 | 客户送达视图 | 说明 |
|---|---|---|
| `id` | 保留 | 详情路由的键 |
| `released_at` | 保留 | 客户要知道结论有多新（表现层再加时效提示） |
| `advisor_name` | 保留 | 客户故事「看到方案由哪位顾问出具」 |
| `disclaimer` | 保留 | 结构的一部分，由模板附加 |
| `allocation_suggestion` | 保留 | 配置建议 |
| 产品清单 | 保留 `product_code` / `product_name` / `product_type` / `risk_level` / `expected_return` / `term_days` | 客观已披露要素 |
| `composite_score` / `score_breakdown` | **去掉** | 排序依据是顾问判断排序是否合理的材料 |
| `reason` | **去掉** | 顾问举证的口气，且引用了画像标签（画像在客户可见视图之外） |
| `warnings` | **去掉** | 文案是写给顾问的（「请核实后再采用」「生成方案前请先确认处置情况」），并含风控预警摘要 |
| `content_classification` | **去掉** | 内部内容分类词汇 |
| `customer_id` / `advisor_id` / `draft_id` | **去掉** | 内部标识；客户由令牌圈定，不需要也不该在响应里回显 |

### 接口

- `GET /api/customer/advisory/plans` — 该客户的定稿列表，按 `released_at` 倒序。**无已放行方案时返回空数组，不是 404。**
- `GET /api/customer/advisory/plans/{final_id}` — 一份定稿。`final_id` 不属于调用者时返回 **404**（不是 403：不确认他人资源是否存在）。
- `GET /api/customer/advisory/plan` — 语义仍是「最新一份」，404 语义不变，只是响应改为客户送达视图。
- 三者共用 `serialize_final_for_customer`，挂在 `app/api/advisory.py` 已有的 `customer_router`（prefix `/api/customer/advisory`）下，读逻辑放 `app/advisory/final.py`。

`/plans/{final_id}` 是全仓第一个客户侧「按 id 取自己资源」的接口：它不像 `/plan` 那样由 `auth.subject_id` 天然圈定，越权检查必须显式写。

### 客户侧 `advisory-requests` 的序列化

`_serialize`（`backend/app/advisory_request/service.py:53-61`）返回的 `customer_id` 一并去掉，贯彻「客户侧响应不含内部标识」。这会让两处既有断言失效（见 Testing Decisions）。

### 客户端页面的组织

- 路由：`/advisory`（name `advisory`）+ `/advisory/plans/:finalId`（name `advisory-plan`）；`CustomerShell.vue` 的 `navItems` 增加第 5 项「我的方案」，`key` 与 path 同名（沿用既有约定）。
- 落在 `apps/customer/src/advisory/` 域内（该域已有 `api.ts` / `types.ts`），不新建 `views/`。
- `products/AdvisoryRequestList.vue` 迁入 `advisory/`；产品筛选页保留「请顾问出具方案」按钮，`requestAdvisory()` 成功后跳转 `/advisory`。
- 详情页展示：出具顾问、放行时间、时效提示、产品清单、配置建议、免责声明。不展示综合得分、排序依据与推荐理由。
- 空状态分两级：无定稿但有请求 → 渲染请求进度；两者都无 → 「还没有提交过方案请求」+ 前往产品筛选的按钮。

### 顾问侧回看

- `AdvisoryWorkspace.vue` 的历史表加「查看」列，复用已存在的 `openReview(draft_id)`。
- `AdvisoryReviewPage` 在 `decided`（已放行 / 已驳回）状态下：标题由「审核」改为「查看方案」，面包屑同步；「返回队列」按钮文案改为「返回投顾助手」——它回到的是工作台，不是审核队列。
- 审核决定面板已经由 `v-if="isAdvisor && !decided"` 挡住（`AdvisoryReviewPage.vue:208-219`），无需新增逻辑；只改标题与返回文案。

## Testing Decisions

沿用两个 seam。

### Seam 1 — 后端 HTTP 层

- **客户 A 的令牌按 id 读取客户 B 的定稿 → 404**
- 尚未放行任何方案时：`/plans` 返回空数组，`/plan` 返回 404
- **客户侧方案响应里不出现 `warnings`、`composite_score`、`score_breakdown`、`reason`、`content_classification`、`customer_id`、`advisor_id`、`draft_id`**
- 放行后 `/plans` 里出现该定稿，且 `allocation_suggestion` 与顾问放行时提交的一致（不是 AI 原稿的）
- 顾问编辑后放行，AI 原稿仍可按原内容读到（原稿不可改）
- 客户侧 `advisory-requests` 响应里不出现 `customer_id`

**要改写的既有断言**（语义不变，比的是裁剪后的形状）：

- `backend/tests/test_advisory_review.py:250-266`、`:269-285` —— `customer_view["candidates"] == draft["candidates"]` / `== edited_candidates`，现在要比客户送达视图的产品清单
- `backend/tests/test_end_to_end_customer_journey.py:538-545` —— 同上
- `backend/tests/test_advisory_request.py:106-114`（断言 `created["customer_id"]`）与 `:125-132` —— 后者要换一种方式证明伪造的 `customer_id` 不生效：改为断言这条请求出现在客户 A 的列表里、不出现在客户 B 的列表里（这比回显 `customer_id` 更贴近它要守的东西）

### Seam 2 — Vue 组件挂载

- 「我的方案」页：有定稿时渲染列表；无定稿但有请求时渲染请求进度；两者都无时渲染引导空状态
- 详情页渲染配置建议、产品清单、出具顾问、放行时间与免责声明；**不渲染综合得分、排序依据与推荐理由**
- 侧边栏存在第 5 项且能到 `/advisory`
- 产品筛选页提交成功后跳转到 `/advisory`
- 顾问侧历史表每行可点进审核页路由
- 审核页在已放行状态下标题为「查看方案」，且不存在放行 / 驳回入口

## Out of Scope

- 推送式通知渠道（站内信、短信、邮件）——沿袭 `advisory-agent-and-review-flow` 的排除
- 「已送达 / 已读」回执，以及客户侧的任何确认动作（Q4）
- 方案的有效期与失效（Q7：只做呈现层的时效提示）
- 客户对方案的反馈、追问与二次沟通
- 方案的 PDF 导出与排版
- 面向客户的推荐理由重写（Q12：不展示它，而不是改写它）
- 顾问可看范围的扩权（Q9：仍只看自己审核过的）
- 客户经理视角
- 方案页的图表（配置建议以文字列表呈现，不新增图表封装）

## Further Notes

- **这是对 Q17 的显式推翻，但它不是「终于发现了遗漏」**：Q17 当时的判断——缺口是记录在案的、要补得先回答三个问题——依然正确。本 slice 回答的正是那三个问题：客户在什么场景下看（提交请求之后回来查结果）、看完留不留痕（不留）、放行后又改版了怎么办（每份定稿各自独立留存，客户可回看历史）。
- **顾问定稿不可改这条没有被软化**：客户能回看多份定稿，每一份都是放行那一刻的快照；「改版」的唯一路径是重新生成 + 重新审核，不是修改已送达的内容。
- **容易踩的一处**：新增的按 id 取定稿是客户侧第一个不靠令牌天然圈定范围的接口。以后再有同类接口，越权检查都要显式写，别指望 `require_customer` 顺手替你兜住。
- **第二处容易踩的**：内部端的 `AdvisoryReviewPage` 同时是「审核」与「回看」两个场景，靠 `decided` 分形态。往该页加功能时要先问它此刻代表哪一个。
