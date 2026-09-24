# 开发顺序

原则：先切一刀端到端最薄的完整链路，再横向加宽。任何时点被迫停下，手上都应有一个能演示的完整状态。

## Spec 索引

每份 spec 在 `.scratch/<slug>/spec.md`，自包含，标注了前置依赖。

| 顺序 | Slug | 覆盖 |
|---|---|---|
| 1 | `foundation-and-customer-service-slice` | 地基 + 智能客服 Agent + 客户端登录与对话 |
| 2 | `internal-workbench-shell` | 内部工作台外壳（路由、角色导航）+ 知识库管理界面 |
| 3 | `customer-profiling-and-suitability` | 画像、风险评测、适当性硬过滤、候选池 |
| 4 | `product-screening-and-customer-assets` | 产品筛选 + 客户端资产页（配置图、风险分布图）+ 持仓穿透 |
| 5 | `data-analysis-agent` | 语义视图 + NL2SQL + 查询界面 |
| 6 | `advisory-agent-and-review-flow` | 投顾助手 Agent + 审核流 + 目标实际对比图 |
| 7 | `knowledge-graph-and-graphrag` | Neo4j 投影 + GraphRAG + 图谱关系图 |
| 8 | `risk-monitoring-agent` | 规则引擎 + 预警 + 工单 + 事件广播 |
| 9 | `memory-confidence-and-integration` | 三层记忆 + 置信度重排 + Agent 协作 + 降级 + 回放模式 |

四个 Agent 分别落在 1、5、6、8；第五个 Agent（业务操作 Agent，见 ADR-0017）落在横切 slice `operation-advice-and-customer-trading`，它同样进内部工作台。四张 ECharts 图分别落在 4（两张）、6、7。

横切 slice（不占串行链上的位置，可随时插入）：`frontend-rebuild` —— 按 `02-企业浅色.html` 从 0 重写两个前端（三栏内部工作台 / 两栏客户应用），取代 `frontend-restyle`。它不依赖任何未完成的后端能力，拆为三份 issue：shared 地基 → customer 应用 → internal 应用。`frontend-rebuild` 未合并前不要动 `apps/*/src`，否则两端会各自漂移。

另一条横切 slice（2026-09-19）：`advisory-plan-visibility` —— 投顾内容的送达面，客户侧「我的方案」页 + 顾问侧回看已放行内容。它显式推翻 `frontend-rebuild` 的 Q17（「客户侧不新增我的方案页」），理由见该 spec 的 Further Notes。拆为三份 issue：客户侧接口 → 客户侧页面 → 顾问侧回看（第三份不依赖前两份，可并行）。

再一条横切 slice（2026-09-19）：`operation-advice-and-customer-trading` —— 客户交易与操作建议。它补的是风控的**输入端**：风控那一侧（规则、算子、分级、预警、工单）本来就是完整的，缺的是「交易从哪来」——交易事件在应用里没有任何真实触发点，唯一入口是需员工身份的内部接口，而种子数据又整批绕过规则引擎，于是「现在的风控监测不起作用」其实是**没有输入**，不是判断不对。本 slice 给客户加上申购、赎回、转账（含资金账户与可用余额），给客户经理加上业务操作 Agent（第五份配置）与操作建议（客户经理发起 → 顾问放行 → 客户可见 → 客户决定），并让这些操作成为交易事件的真实来源。拆为十份 issue，顺序推进；**第四份做完就有可演示的完整状态**（客户发起 50 万转账 → 预警列表出现对应预警）。它**修改**三处已实现的既有决定（`product-screening-and-customer-assets` 的「真实申购赎回支付」排除、`risk-monitoring-agent` 的交易事件来源、`advisory-agent-and-review-flow` 的审核表），清单见该 spec 的头表。

再两条横切 slice（2026-09-21，同一次访谈产出，编号共用）：

- `advisor-review-reminder` —— 顾问的待审核提醒。审核队列只有在顾问主动走进 `/advisory` 时才存在，数字也只活在那页的卡片标题里（`AdvisoryWorkspace.vue:37`）。本 slice 把它钉到「投顾助手」导航项的待办计数上（`CONTEXT.md` 新增词条），复用既有队列接口而**不新增 count 接口**（两个口径迟早漂移，而「角标说 3、点进去是 2」正是提醒失效的形态），只对理财顾问。**无后端改动**，代价明确认下：只在自己刷新时才对，不加轮询、不加 SSE。
- `operation-advice-product-choice` —— 操作建议的产品与金额由发起人决定，业务操作 Agent 收窄为只写理由（新增 ADR-0021）。它**修改** `operation-advice-and-customer-trading` 的 `#06` 两处已实现决定（「产品/金额/理由由 Agent 给出」与「申购取起投、赎回取全部份额」），**不改**「赎回的产品须在候选池内」这条硬保证，也不动「成交口径只有一处」。赎回因此从「全部」变成携带一个具体份额数（草案加一列），接受时按它执行。

再一条横切 slice（2026-09-21）：`collapsible-sidebars` —— 左右栏折叠/展开。两端左导航可折叠成 64px 图标条（internal 的 `sidebar-footer` 折叠为图标+角标），internal 右检查器可完全隐藏（顶栏开关）；折叠状态全局、按端 localStorage 持久化、默认展开。纯前端、无后端改动、无 ADR、`CONTEXT.md` 零改动。拆三份 issue：shared 壳受控折叠 → customer 接线 → internal 接线（含检查器开关与 footer 折叠态）。

再一条横切 slice（2026-09-22）：`customer-deposit` —— **资金账户的入口**。出口一直有（申购、转账），入口没有：`available_balance` 的四个写入点除赎回外全是「减少」，而开户建出的资金账户余额为 0，于是新客户在应用里**永久不能动钱**（能登录、能做完风评、能看到产品，然后被「可用余额不足」永久挡住），演示只能靠种子给足余额、花完就换一位客户重来。本 slice 给客户加上**充值**：钱从机构之外进入自己的资金账户，余额增加；它是交易流水的一类（独立表 `fin_deposit`，ADR-0019 的延续，客户侧合并读升为**三表扇入**）、也照常是一笔交易事件（风控第一次看得见入金，13 条只建在金额/笔数/时段上的规则直接吃它），受理通过即入账、不记来源、只对客户自助开放。受理侧只拦「金额必须为正」——**大额入金交给规则引擎而不在受理侧拒收**。它**推翻**两处已实现的既有决定：`operation-advice-and-customer-trading` 的 Q20（「种子给足余额，不做入金」）与 `onboarding-funding-account-and-target-allocation` 的 Out of Scope 第一条（「入金仍然不在范围内」），清算单见该 spec 的头表。拆为四份 issue，已全部完成；**第一份做完就有可演示的完整状态**（客户端充值一笔 → 余额涨 → 预警列表出现对应预警）。

再一条横切 slice（2026-09-23）：`analytics-chat-ui` —— **数据分析的界面换成对话形态**。多轮追问在后端早就成立（提问带着 `session_id`，后端拿它做 Redis 短期记忆，`select_views_node` 甚至专门把上一轮的提问并进视图匹配的语境），但界面是表单范式、结果只有一个槽、每次提问覆盖上一条——问答不成串，于是「可以追问」在界面上不成立。本 slice 把主区换成一条对话线程（用户气泡 + 助手气泡，底部多行输入），助手气泡里按固定次序装着口径解读 / 结果表 / 可折叠 SQL / 元信息，五种业务码（1101–1105）各自成文案；**逐字感用前端打字机复刻**（客服的推流本身也是「整轮跑完再逐字转帧」，无需新流式端点）；历史查询从右栏搬进顶栏抽屉、第三栏因此塌陷为两栏。会话从页面级改为登录级——`session_id` 缺省取登录凭证里的 `sid`，这是**本 slice 唯一的后端改动**——并补一个页头「清空对话」作为换话题的出口，因为这次改动连同线程持久化一起关掉了员工今天唯一的重置手段（刷新即新会话）。**风控问答不动**：它共用同一份请求模型却是另一页，因此两页会话寿命不同，这一处不一致已记为已知决定而非疏漏。拆五份 issue，顺序推进。

再一条横切 slice（2026-09-23）：`customer-nl2sql` —— **客户端数据查询，智能客服接入 NL2SQL**。数据分析的 NL2SQL 链路（语义视图、只读校验、受限账号、fail closed）员工侧早已完整，但客户身份落不进现有视图——`va_*` 的行级条件是员工侧口径。本 slice 给客服图的 `classify` 增加数据查询分支，确定性路由到复用的 analytics 链路；新建四张客户域语义视图（持仓、流水、资金账户、风险测评结论）行级锁凭证客户，员工侧五视图一行不动。边界钉在 ADR-0025：允许客户拿风险承受等级筛产品（Cn 筛 R1–Rn）但**只筛不排序、按产品代码排序**，因此仍是事实性内容、不违反「客服工具集内不存在推荐类能力」；结果以文本解读送达（SSE 与前端零改动），失败/超时降级留痕、**绝不回退到知识检索**，白名单外（画像、服务记录、风控预警）明确告知不可查。纯后端，不依赖任何未完成的 slice。拆三份 issue，顺序推进，第二份做完即有可演示的完整状态。

再一条横切 slice（2026-09-24）：`risk-rule-management` —— **规则的编辑器**。`risk-monitoring-agent` 的用户故事 22 承诺「规则存在库中而非硬编码，so that 调整阈值不需要改代码发版」，但只兑现了一半：两个 `PATCH` 让专员能改既有规则的灵敏度，20 条种子却仍是唯一来源（`rules.py:84-322`），想加一条本地口径的规则只能改代码出迁移。本 slice 补上创建、修改与删除，同时把可写的边界钉死：专员能配的是**组合**（在给定的字段、算子与值域里挑），不是**表达**（拼逻辑、造新算子）——后者会让 `fin_risk_rule` 变成存在数据库里的代码，而 `operators.py:9-11` 与 `fields.py:3-8` 两处开篇都写着集合是有限且封闭的。顺带修掉一个潜伏的崩点：三条 CHECK 各自守住一列，却不校验两列搭配，于是 `field = product_id` + `operator = gt` 两列各自合法、DB 收下，直到**下一笔交易到达**才抛 `TypeError`；写入侧因此加三档校验（名录 → 字段×算子允许矩阵 → 阈值值域）。它**推翻** `risk-monitoring-agent` 的 Out of Scope 第二条（「规则的可视化编辑器（本 slice 只做查看与启停）」）并**修改**其 `#01` 的三处（启停理由从可空收紧为必填、`category` 补一条 DB CHECK、种子从「只补缺失」改为「表为空才播种」），清单见该 spec 的头表。新增两条 ADR：0026（规则的身份就是它的判定形状——判定形状不可改，换形状只能删除重建）、0027（删除是软删、编号永不复用、种子只在建库时播种）。拆五份 issue：数据层与种子语义 → 允许矩阵与值域校验 → 三个写接口与留痕 → 规则管理界面 → 端到端收口，顺序推进；**第四份做完就有可演示的完整状态**（专员新建一条必然命中的规则 → 补录一笔交易 → 预警列表出现对应预警，而**已有交易不产生任何新预警**——不做回算是一条明确的决定，见该 spec 的 Q18）。纯后端加内部端，不依赖任何未完成的 slice（`risk-monitoring-agent` 五份 issue 均已 `implemented`）。

上面两份新 spec 共拆 7 份 ticket（`advisor-review-reminder` 2 份：计数 store → 导航角标；`operation-advice-product-choice` 5 份：可选项端点 → 发起受理接手产品与金额 → 赎回按份额成交 → 发起表单 → 端到端与既有断言收口）。全部 spec 已拆成 ticket，存于 `.scratch/<slug>/issues/`，共 106 个（本行此前写 83，已经过期——`list-pagination`、`session-renewal`、`rag-retrieval-upgrade` 三条 slice 的 issue 也不在本节列出；数字按 `.scratch/*/issues/*.md` 实际清点，2026-09-24。其中 `customer-deposit` 的四份在链尾：它的前置 `operation-advice-and-customer-trading` 与 `onboarding-funding-account-and-target-allocation` 都已实现，因此那四份里的 #01 可直接开始）。依赖是一条串行链：每份 spec 的第一个 ticket 被上一份 spec 的最后一个 ticket 阻塞，spec 内部亦为顺序推进。唯一的例外是 `foundation-and-customer-service-slice #07`（共享包边界检查），它只依赖 #01，可提前做。

**当前 frontier**：待重新核对。`.scratch/*/issues/*.md` 里的 `Status:` 标记已经落后于代码——例如 `advisory-plan-visibility` 的三份仍标 `ready-for-agent`，但 `apps/customer/src/advisory/AdvisoryPlanPage.vue` 与 `backend/app/advisory/final.py` 的 `serialize_final_for_customer` 都已经存在；`advisory-agent-and-review-flow` 的 #01–#03 同理。在逐份核对 `Status:` 之前，本行不作断言——写一个过时的答案比留白更容易误导人。
（2026-09-24 只补一条已核实的：`risk-rule-management` 的 5 份 issue 已就位，其 #01 的前置 `risk-monitoring-agent #05` 标记为 `implemented` 且对应代码在 `backend/app/api/risk_query.py`，所以这一条的起点可用——但这不改变上面那句「其余状态待人逐份核对」的结论。）

七条护栏测试（ADR-0009）分布：

| 护栏 | 所在 ticket |
|---|---|
| 1 适当性硬过滤 | `customer-profiling-and-suitability #03` |
| 2 身份域隔离 | `foundation-and-customer-service-slice #03` |
| 3 只许只读查询 | `data-analysis-agent #02` |
| 4 产品列表不按收益率排序 | `product-screening-and-customer-assets #01` |
| 5 未审核内容不可送达 | `advisory-agent-and-review-flow #03`、`operation-advice-and-customer-trading #07` |
| 6 shared 不含业务语义 | `foundation-and-customer-service-slice #07` |
| 7 交易受理校验不可绕过 | `operation-advice-and-customer-trading #04` |

## 第 0 步 · 地基

- [ ] pnpm workspace 骨架：`backend/`、`apps/customer/`、`apps/internal/`、`packages/shared/`
- [ ] `docker-compose.yml` 六个容器：mysql(3307)、redis(6380)、etcd、minio(9001)、milvus(19531)、neo4j(7688)
- [ ] MySQL 11 张表与迁移脚本（`sys_customer` / `sys_employee` 拆表，见 ADR-0004）
- [ ] FastAPI 骨架：统一响应格式 `{code, message, data, trace_id}`、全局异常处理、分级日志
- [ ] Mock 数据：5 位测试客户、产品目录、交易流水、持仓

## 竖切 · 客服链路端到端

这一刀很薄，但它一次性验证了后面所有东西依赖的六件事：身份域、响应格式、SSE、引用契约、Element Plus 主题基座、shared 层边界。

- [ ] 两个身份域的 JWT 签发与校验（不同 audience）→ **护栏测试 2**
- [ ] 文档解析 → 分块（512 token / overlap 64）→ Embedding → Milvus 入库
- [ ] 导入 40 组 FAQ 作为初始知识库
- [ ] 知识检索 + 强制引用（检索不到依据时不作答）
- [ ] LangGraph 运行时骨架 + 智能客服 Agent 配置（见 ADR-0007）
- [ ] SSE 流式输出
- [ ] `apps/customer`：登录页 + 对话页 + 可点击引用角标
- [ ] 至此应能演示：登录 → 提问 → 带引用的流式回答

## 横向加宽

### 画像与适当性

- [ ] 风评问卷（16 题）+ 评分 → 风险承受等级 C1-C5
- [ ] 画像研判引擎：四维度加权 + 硬性门槛熔断
- [ ] 置信度基础版：来源初始值 + 证据增益 + 冲突惩罚 + 时间衰减
- [ ] 适当性硬过滤与候选池 → **护栏测试 1**

### 产品与客户端资产页

- [ ] 产品筛选（强制按产品代码排序，见 ADR-0005）→ **护栏测试 4**
- [ ] `apps/customer` 资产页：持仓列表 + 实际配置饼图 + 持仓风险等级分布
- [ ] 持仓穿透（MySQL 递归 CTE）

### 数据分析 Agent

- [ ] 语义视图（已脱敏、内置行级权限的只读视图）
- [ ] NL2SQL：动态 Schema 注入 + few-shot + 安全校验 → **护栏测试 3**
- [ ] 结果解读与表格渲染
- [ ] `apps/internal` 外壳：路由、侧边栏按角色渲染、登录

### 投顾助手 Agent 与审核流

- [ ] 产品推荐：候选池 → 图谱增强 → 综合排序 → 推荐理由
- [ ] 资产配置建议
- [ ] AI 原稿 / 顾问定稿两版本留存
- [ ] 审核队列与放行驳回（LangGraph interrupt）→ **护栏测试 5**
- [ ] 内部端画像面板：目标配置 vs 实际配置对比条形图（见 ADR-0006）
- [ ] 客户侧「我的方案」页与顾问侧回看已放行内容（`advisory-plan-visibility`）

### 知识图谱与 GraphRAG

- [ ] MySQL → Neo4j 单向同步脚本（投影读模型，见 ADR-0002）
- [ ] 图谱模型：Customer / Product / RiskLevel / Industry / FundManager
- [ ] Cypher 查询封装为 Tool
- [ ] GraphRAG 融合排序（向量 Score × α + 图谱 Score × β）
- [ ] 内部端图谱关系图（ECharts graph 系列）

### 风控监测 Agent

- [ ] 交易事件先落库再广播
- [ ] 20 条风控规则的声明式规则引擎（阈值判断不经过 LLM）
- [ ] 预警分级（单规则 / 多规则交叉 / 多源验证）
- [ ] 工单派生与处置流程
- [ ] Redis Pub/Sub 事件总线
- [ ] 内部端预警列表、预警详情、工单处置页
- [ ] 规则管理支持创建、修改、删除（`risk-rule-management`：规则编辑器 + 写入侧三档校验 + 软删与种子语义，见 ADR-0026 / ADR-0027）

**输入端是本节的缺口**：以上全部做完之后，「交易事件由接口提交」这条排除会留下一个空转的监测——应用里没有任何真实触发点。补它的是横切 slice `operation-advice-and-customer-trading`（客户交易 + 种子历史交易回放），以及其中的护栏 7（内部补录只对风控专员开放）。

### 记忆与置信度

- [ ] 短期记忆（Redis 会话 + Token 预算截断）
- [ ] 中期记忆（画像缓存 Cache-Aside）
- [ ] 长期记忆（Milvus + Neo4j + MinIO + MySQL）
- [ ] 会话归档（脱敏后写入）
- [ ] 综合置信分重排（四场景权重）
- [ ] 周期校准任务

### 收尾

- [ ] `packages/shared` 业务语义构建期检查 → **护栏测试 6**
- [ ] 多 Agent 协作场景（风控 → 投顾、客服 → 风控）
- [ ] 端到端客户旅程
- [ ] 错误重试与降级（指数退避、Milvus 超时降级、Neo4j 超时跳过）
- [ ] 回放模式预置数据（见 ADR-0008）
- [ ] 前端从零重做（`frontend-rebuild`：按 `02-企业浅色.html` 重写两端骨架与页面，取代 `frontend-restyle`）
- [ ] 数据分析界面改对话式（`analytics-chat-ui`：数据分析页换成线程与追问，历史查询进抽屉，会话改走登录凭证）
- [ ] 客户端数据查询（`customer-nl2sql`：客服图接 NL2SQL 分支 + 客户域语义视图，见 ADR-0025）
- [ ] 答辩材料：PPT、API 文档、数据库文档、架构说明
- [x] 端到端演示脚本：`docs/demo-script.md`（`operation-advice-and-customer-trading` 的验收标准、重度预警的讲法与断言索引）
- [ ] 会议纪要补齐（评分表 -5，成本近零）

## 待办的登记项

- [ ] Gitea remote 尚未确定，确定后 `git remote add origin ...`
- [ ] `backend/.env` 填入真实 key 后，把两个 provider 从 `fake` 改为 `openai_compatible`
- [ ] `EMBEDDING_DIMENSION=1024` 必须在建 Milvus 集合前确认，写入后不可改
