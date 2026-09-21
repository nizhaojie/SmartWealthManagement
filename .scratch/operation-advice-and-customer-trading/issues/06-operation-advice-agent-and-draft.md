# 06 — 业务操作 Agent 与操作建议原稿

**What to build:** 客户经理第一次有了提建议的手段：为名下客户选定场景，业务操作 Agent 在**候选池内**产出操作建议（一个产品、一个方向、一个金额、一条理由），落成 AI 原稿，等顾问放行。这是第五份 Agent 配置，与投顾助手共用同一套运行时（ADR-0017）。

**Blocked by:** 05 — 审核流水线泛化出内容类型

**Status:** implemented

- [x] `AgentConfig` 增加第五份配置：业务操作 Agent
- [x] 同步「四个 Agent」的既有表述：`backend/app/agent/registry.py` 与 `config.py` 的模块注释、`backend/tests/test_end_to_end_customer_journey.py`（旅程按注册表列出的 Agent 逐一打通）、以及 `docs/system-architecture.md` 的「四个 Agent 与功能」一节。**这些是有意的成组改动，不是顺手改注释**——漏掉测试那一处，第五份配置会永远不进端到端旅程
- [x] 工具集：候选池查询、客户持仓与资金账户查询、建议生成；**不引入推荐类的第二套排序**，与投顾助手的分工在产物
- [x] 候选池已完成适当性硬过滤，**Agent 不重新做适当性判断**，提示词里不出现适当性规则
- [x] 输出的内容分类默认为**投顾内容**
- [x] 建议本体的三条硬边界：**一次只对应一个产品一个方向**、**金额必填**、**禁止收益预测与配置比例表述**（后者一旦出现，「操作建议」与「配置方案」就重合了）
- [x] 理由必填——顾问要审的就是它
- [x] 生成只开放给**客户经理**，且只对**名下客户**（复用 `manager_id` 归属关系）
- [x] 原稿落库后不可修改（沿用既有的 AI 原稿约束）
- [x] 断言：客户经理只能对名下客户发起；理财顾问与风控专员发起被拒绝
- [x] 断言：生成的建议里产品全部来自候选池（护栏 1 的延续）

**实现落点：** `backend/app/agent/config.py`（`OPERATION_ADVICE_CONFIG`）、
`backend/app/agent/registry.py`（第五个条目与入口路由）、
`backend/app/operation_advice/`（`draft.py` 载荷落库与序列化、`reasons.py` 理由、`graph.py` 运行时图、
`service.py` 生成入口、`schemas.py`）、`backend/app/api/operation_advice.py`（发起路由，注册在 `main.py`）；
被复用而小改的既有模块：`app/funding_account/service.py`（余额的数值形式）、
`app/customer_assets/service.py`（持仓份额）、`app/order_acceptance/service.py`（成交口径公开成
`purchase_cost` / `redemption_amount`）、`app/advisory/review.py`（决定落库抽成 `record_decision`，
两类内容的图共用一份）；
「四个 Agent」表述同步：`app/agent/registry.py`、`app/agent/config.py`、`app/api/agents.py`、
`app/agent/classification.py`、`app/analytics/service.py`（改为「数据分析与风控监测两个 Agent」——
这条链路只有那两个 Agent 用）、`tests/test_end_to_end_customer_journey.py`、
`tests/test_risk_natural_language_query.py` 的注释、`docs/system-architecture.md`；
测试 `backend/tests/test_operation_advice_draft.py`（新增，10 条）。

### 几处写下来的决定

**发起场景就是方向，产品/金额/理由由 Agent 给出。** 请求体只有一个 `direction`（申购 / 赎回）：
方向是客户经理的判断（他要不要这只票），产品、金额与理由是 Agent 在候选池内算出来的。不
把方向也交给 Agent 猜——它查到的事实里没有「客户想买还是想卖」这一项，硬猜就是编一个动机
塞进审核材料。合法方向与投顾助手的侧重同一口径，在服务里判定（`未知的操作方向`）。

**金额只有一个来源：产品要素与持仓，且与受理侧共用成交口径。** 申购取产品的起投金额、
赎回取该持仓的成交金额（份额 × 净值），两个数都从 `app.order_acceptance` 的
`purchase_cost` / `redemption_amount` 取。这不是顺手抽函数：Agent 若自己再算一遍费率与
净值，差一分钱就会生成一条**当场会被拒绝**的建议，而这条建议在审核页上看起来完全正常。
反过来，Agent 因此也不需要「可用余额是否够」之外的金额裁量，不引入第二套金额算法。

**申购要求产品买得起，赎回要求持仓在候选池内。** 申购在候选池内「未持有」的产品里排序后
取第一只**买得起**的（余额 ≥ 金额 + 手续费），一只都买不起时报错而不是给一条注定被拒的
建议；赎回只在「持有 ∩ 候选池」里选，因为「生成的建议里产品全部来自候选池」是一条硬保证，
不因方向不同而放宽——代价是停售或等级下降后的持仓赎回建议做不出来，那是真实业务里的
另一条口子（客户可以直接发起赎回，不受这条限制）。

**理由不复用方案的 `build_reason`。** 那条理由是为配置方案写的，带「预期年化收益 X%，
处于候选池内较高水平」与持有周期的措辞。操作建议一旦出现收益预测或配置比例表述，三条硬
边界里的第三条就破了。这里的理由只用两份事实：候选池给出的产品要素（风险等级、期限）与
客户自己的持仓、可用余额——正好是这份配置声明的三件工具能查到的全部东西，因此理由里的
每一句都可被顾问逐项核对。

**放行不产生第二份载荷。** 方案放行时顾问会编辑候选池与配置建议，因此要落一份顾问定稿
（ADR-0016 的送达视图来自定稿）。操作建议没有可编辑的字段，原稿又是不可修改的，所以
「放行」只把审核记录置为已放行——原稿本身即送达版本。将来若允许顾问改金额或理由，需要
先加一张定稿表，而不是就地改原稿。

**归属与角色是两道门，分开写。** 角色在入口依赖里声明（`require_employee_role(客户经理)`），
归属在服务里判定（`app.customer_scope` 的 `is_under_management`）。混在一处写，将来给别的
角色开一个口子时就会顺手把归属那一道也放开。

**决定落库收进了流水线一份（`app.advisory.review.record_decision`）。** 两类内容的图在各自的
finalize 里都只做「置状态 + 写审核留痕 + 提交」，分头写两遍的话，改状态集时总有一处会漏，
而漏掉的那一处表现为「这份内容永远停在处理中」，不会有任何断言当场失败——这正是 ADR-0020
说「一条流水线」时要防的那种漂移。

### 与 #07 / #09 的交接

`app.advisory.review` 的 `claim_review` / `resume_review` 现在对操作建议直接可用：图已按
`CONTENT_TYPE_OPERATION_ADVICE` 登记，且用同一个 `ADVISORY_CHECKPOINTER` 编译（`#05` 的交接
契约）。放行与驳回在中断处续跑——测试里直接调用那一对函数钉住了它，**放行 / 驳回的 HTTP
入口、客户侧读取与客户决定属于 #07**；审核页按内容类型渲染载荷、客户经理视角的入口与
进度属于 #09。

放行只置状态、不再产生第二份载荷这件事，是 #07 读取客户侧送达内容的依据：**审核记录为
「已放行」的原稿就是可送达的那一份**，未放行的原稿在客户侧一律读不到。
