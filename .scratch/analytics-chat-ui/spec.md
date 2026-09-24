# 数据分析改成对话式界面（内部工作台 · 客服形态 + 追问）

Status: ready-for-agent

**后续推翻（2026-09-24，见 `issues/06-composer-and-empty-state-polish.md`）**：Q14（Ctrl+Enter 发送 / Enter 换行）、Q9 的「入口挂顶栏」、以及「空态示例问题点击直接发问」这三条已被 ticket 06 改掉——输入区改回单行回车发送（与客服侧同形），「历史查询」回到页头「清空对话」右侧，示例问题改为只填入输入框。上面的访谈清单是当时的记录，不追改。

前置：`data-analysis-agent`（已实现，语义视图 + NL2SQL + 查询界面）、`frontend-rebuild`（已实现，三栏外壳与设计令牌）、`list-pagination`（已实现——右栏分页控件就是它留下的）。

**本 slice 不新增 ADR。** 判定见 Further Notes。

## Problem Statement

**「追问」在后端已经成立，在界面上看不出来。** 数据分析的提问带着 `session_id`（`apps/internal/src/analytics/DataAnalysisWorkspace.vue:13` 的页面级 `crypto.randomUUID()`），后端拿它做 Redis 短期记忆，「那上个季度呢」确实听得懂——`select_views_node` 甚至专门把历史里用户问过的话并进视图匹配的语境（`backend/app/analytics/graph.py:52-60`，注释直写「多轮追问本身可能不含任何视图关键词，上一轮的提问才是语境」）。但界面是**表单范式**：一个输入框 + 一个结果区，`result` 是单槽（同文件 `:17`、`:60`），每次提问覆盖上一条。问答不成串，上一轮不可见，于是「可以追问」这件事在界面上不成立——这是**界面**的问题，不是能力的问题。

**能追问的前提是问答留成线程。** 只要主区还是「表单 + 单个结果区」，上一轮就必须被覆盖，追问就永远是「重新问一个」。

**智能客服的形态不能照抄。** 客服侧的气泡只渲染纯文本与引用角标（`apps/customer/src/chat/ChatPage.vue:133-155`），没有表格、没有 markdown、没有卡片。而数据分析的产物恰好是**一张表 + 一段口径解读 + 一段可折叠的 SQL + 元信息**。抄它的形（气泡、底部输入框、线程、打字机）是对的，抄它的内容渲染是错的。

**internal 侧没有可复用的聊天壳。** 客服的消息列表、气泡、空态、输入框全部内联在 `ChatPage.vue` 里，`ChatHistoryDrawer.vue` 里还抄了第二份同样的气泡 markup；`packages/shared` 里没有任何聊天组件。internal 照做会成为第三份。

**右栏与主区的既有约定也要一并处理。** 这页的主区在 `frontend-rebuild` 时明确取消了限宽（「宽表不再出水平滑动条，客户主区改满宽」），而右栏第三栏今天被「历史查询」占着（`analyticsHistoryRail.spec.ts` 整个文件的存在理由就是证明它真的落在第三栏）。

## Solution

**把主区从表单改成一条对话线程**：用户气泡在上、助手气泡在下，助手气泡里装着完整的一轮产物（口径解读 + 结果表 + 可折叠 SQL + 元信息与各种警示），底部固定一个多行输入框。表单消失，提交流程变成「发出一条消息」。

**追问因此自然成立**：线程累积可见，上一轮的问答就在上面，`session_id` 继续把它接上。

**会话从「页面级」改为「登录级」**：`session_id` 不再由页面生成，改由后端缺省取登录凭证里的 `sid`。这是 `CONTEXT.md` **会话** 词条的字面落实——「不跨登录延续」由 Redis 白名单保证，而不是靠前端自觉。刷新与切模块不再丢上下文；同时补一个页头「清空对话」作为换话题的出口，因为这次改动关掉了员工今天唯一的重置手段（刷新即新会话）。

**逐字感用前端复刻，不加流式端点**：客服的推流本身也不是模型流式——后端整轮跑完再把定案回答逐字转帧（`backend/app/api/chat.py:87-95`，注释「推流过程本身不再做任何决策」），前端再用 `TYPEWRITER_INTERVAL_MS = 30` 把节奏压回人类速度。同一份观感可以在纯前端拿到，零契约改动。等待期间只给一个诚实的加载态，不演阶段。

**历史查询从右栏搬进抽屉**：右栏因此空掉，第三栏塌陷为两栏（`AppShell` 由 `inspector` 插槽是否存在自动决定，无需传 variant），入口改挂顶栏。抽屉只有一个态——历史记录的详情只有六个字段加一条 SQL，为这点增量加一个导航态是照客服的模板走，而不是按内容量走。

## 访谈结论清单（grill-with-docs，2026-09-23，四轮共 16 问）

### 第一轮

| # | 决定 |
|---|---|
| Q1 | **交互范式的替换（a）**：主区换成对话线程，表单消失；不是「表单保留 + 结果累积」，也不是「只换视觉」。合规呈现面整体搬进助手气泡，一件不能少。 |
| Q2 | **「追问」= 线程内多轮（a）**：系统记得上一句且界面上看得见上一轮。后端已支持，工作全在前端。不做系统生成的候选追问，也不做下钻式追问。 |
| Q3 | **登录级会话（b）**：会话活到登录结束，切模块与刷新都不丢，重新登录即新会话。右栏「历史查询」保持现状——**会话** 与 **审计级留痕** 是两回事，不合并。 |
| Q4 | **只改数据分析（a）**：风控问答不动，`AnalyticsResultView.vue` 原样留给它（新写气泡内的结果组件）。 |
| Q5 | **前端伪流式 + 一条加载态（c）**：拿到整包后由打字机播放解读，零后端改动；不为逐字效果新增流式端点。 |

### 第二轮

| # | 决定 |
|---|---|
| Q6 | **后端把 `session_id` 的缺省值改成登录会话的 `sid`（b）**：`body.session_id or auth.session_id`。破了「零后端改动」，因此明确列为本次**唯一**的后端改动。不采用「前端解 JWT 取 `sid`」（本仓库至今不解析凭证），也不采用「前端自持 UUID 存 sessionStorage」（把「不跨登录延续」从 Redis 白名单降级为前端自觉）。 |
| Q7 | **`sessionStorage` 存整条线程（a）**：含结果行，登出与重新登录即清。数据本就已按语义视图脱敏（`customer_name` 是「姓 + 星号」），且落在浏览器而非服务端。 |
| Q8 | **聊天壳留在 `apps/internal`（b）**：不进 `packages/shared`。仓库的准入标准是「两端都用才进 shared」（`CiteChip` 因单消费者留在 customer 应用内），(a) 是过早抽象，(c) 是范围蔓延。可逆，不新增 ADR。 |
| Q9 | **右栏空掉、第三栏塌陷为两栏，历史查询进顶栏 + 抽屉（c）**——**推翻了本轮的推荐 (a)**。 |
| Q10 | **一个助手气泡装满主区宽度（a）**：解读在上、表格居中、SQL 折叠块在下、元信息与警示贴底。不用限宽气泡（会把刚拆掉的横向滑动条请回来），也不拆成两个气泡（解读与表格必须同时可见）。 |
| Q11 | **诚实的加载态（a）**：助手气泡里只有「正在查询数据…」+ 三点动画，不演「生成查询 → 校验 → 执行 → 解读」这段后端并未告知的过程。 |

### 第三轮

| # | 决定 |
|---|---|
| Q12 | **只动数据分析的会话语义（a）**：后端默认值只写在 analytics 路由那一行，风控问答继续传它的页面级 UUID。**代价明确认下**：两页会话寿命不同，这是一个记在案的已知不一致。 |
| Q13 | **一态抽屉（c）**：列表项自带状态 / 行数 / 时间，SQL 行内折叠展开；不做客服那样的「列表 ⇄ 只读详情」两态。`AnalyticsHistoryDetail.vue` 因此折叠掉，它的「留痕不存结果集」那句话搬到抽屉的脚注。 |
| Q14 | **多行自适应输入框 + Ctrl+Enter 发送（c）**：Enter 留给换行，天然避开中文输入法组字时 Enter 上屏被误当发送；且沿袭这页已有的 Ctrl+Enter 约定。 |

### 第四轮

| # | 决定 |
|---|---|
| Q15 | **页头给「清空对话」（b）**：清 Pinia + `sessionStorage`，生成新 UUID 随请求覆盖——`AnalyticsQueryRequest.session_id` 有值时优先，所以后端不必再改。同时定下「再问一次」= 在当前线程里重问、带着当前上下文。 |
| Q16 | **清空算同一个会话（a）**：「清空」的语义是**丢弃上下文**，不是**结束会话**。唯一能结束会话的事仍然只有重新登录。`CONTEXT.md` 词条只补一句，定义不动。 |

## 关键事实基线

实现时可直接引用，不必重新检索。

| 事实 | 依据 |
|---|---|
| 多轮追问今天成立且后端做得比客服更完整：`select_views_node` 把历史中用户问过的话并进视图匹配语境，`generate_node` 拿到 `history` | `backend/app/analytics/graph.py:52-60`、`:73-82` |
| 客服侧的 `retrieve` 与 `classify` **只看当前这一句、不做指代消解**——数据分析这条链反而是本仓库多轮做得最扎实的一条 | `backend/app/agent/graph.py:165-205` |
| 短期记忆是 Redis 列表，键 `agent:memory:{namespace}:{employee.id}:{session_id}`，TTL 滑动 30 分钟、token 预算 2000、Redis 不可用即降级为空历史 | `backend/app/analytics/service.py:39-41`、`backend/app/agent/memory.py:30-34`、`settings.py:126-127` |
| 两个身份域的 token 都带 `sid`，登录函数一视同仁 | `backend/app/auth/service.py:48`、`backend/app/auth/dependencies.py:51-55` |
| **前端全仓没有任何一处解 JWT**，`createTokenStore` 存的是不透明字符串 | `apps/internal/src/auth/tokenStore.ts`（全仓 grep `atob\|jwt\|decode` 零命中） |
| 客服的推流不是模型流式：整轮跑完再逐字转帧；前端打字机 30ms 压节奏 | `backend/app/api/chat.py:87-95`、`apps/customer/src/chat/ChatPage.vue:19` |
| 客服气泡只渲染纯文本 + 引用角标，无表格 / markdown / 卡片；也没有示例问题与候选追问 | `apps/customer/src/chat/ChatPage.vue:133-155`（全仓无 `follow_ups` 字段、无示例 chips） |
| 客服侧**没有可复用的聊天壳**：消息列表与气泡内联在 `ChatPage.vue`，`ChatHistoryDrawer.vue:165-204` 是第二份同样的 markup | 逐文件核对 |
| 风控问答与数据分析共用同一份 `AnalyticsQueryRequest`；风控前端也自持页面级 UUID | `backend/app/api/risk_query.py:18`、`:44`；`apps/internal/src/risk/RiskQueryTab.vue:15` |
| 失败面是 HTTP 200 + 业务码 1101–1105，**被拒绝的尝试同样留痕** | `backend/app/analytics/errors.py`、`service.py:79-89` |
| 留痕表 `biz_analytics_query_audit` **没有 `session_id` 列** | `backend/app/db/models.py:1030` |
| `AppShell` 的两栏 / 三栏**由 `inspector` 插槽是否存在自动决定**，不额外传 variant | `packages/shared/src/shell/AppShell.vue` 与 `frontend-rebuild` spec 的骨架一节 |
| 历史查询今天在右栏，且有独立 spec 断言它落在第三栏 | `apps/internal/src/analytics/analyticsHistoryRail.spec.ts` 文件头注释 |
| 这页主区在重做时取消限宽，理由是宽表不该出横向滑动条 | 提交 `f1c6452`、`a3c4467` |
| 数据分析结果用 `el-table`，整个模块不引入 ECharts | `apps/internal/src/analytics/AnalyticsResultView.vue:71` |

## Implementation Decisions

遵循 `docs/adr/`。本 slice 直接受 ADR-0009（合规护栏测试）、ADR-0012（三层记忆与会话归档的界线）、ADR-0024（统一分页）约束；ADR-0010（语义视图）与 ADR-0007（单运行时多配置）**不受影响**——本次不碰查询生成、校验与执行。

### 会话与会话标识

- `AnalyticsQueryRequest.session_id` 保持可选。analytics 路由把缺省值改成登录会话：`body.session_id or auth.session_id`（`backend/app/api/analytics.py`）。**这是本次唯一的后端改动**，且只落在这一行。
- 风控问答路由**不动**，继续用请求体里的值。两页会话寿命不同是已知并已认下的不一致，见 Further Notes。
- 前端不再生成 `sessionId` 送出去（`apps/internal/src/analytics/api.ts` 的 `session_id` 由「必填」变为「仅清空后覆盖时才带」）。`types.ts` 里 `AnalyticsQueryInput.sessionId` 改为可选，并写明它的唯一用途。

### 线程与持久化

- 线程存 Pinia store（`apps/internal/src/analytics/` 内，**不进 shared**——Q8），并用 `sessionStorage` 持久化，键按员工隔离（沿用 internal 的 localStorage key 前缀 `wealth-internal-auth` 的命名风格）。
- **登出与重新登录都清空**线程。清空动作挂在既有的登出路径上，不新起机制。
- 序列化有上限：每轮结果行沿用后端的 200 行上限，线程只保留最近 **20 轮**；超出的部分在界面上显示为「更早的一轮已从本页移除」，避免撞 sessionStorage 配额后整条线程写失败。
- 「清空对话」（页头按钮）清 store + sessionStorage，并生成一个新 UUID 随请求覆盖。**它不动审计留痕**——留痕是逐次查询的合规记录，不受界面动作影响。点击需二次确认（会话里有内容时）。
- **线程不是历史记录**：这不是 `CONTEXT.md` 的 **历史记录**（那是客户本人对已结束会话的只读回看），也不进任何归档。本次不新增词条。

### 对话壳与输入

- 落在 `apps/internal/src/` 的应用内目录，与 `analytics/` 并列或在其内（实现时定），**不进 `packages/shared`**。
- 主区结构：`PageHeader` → 消息列表（可滚动）→ 空态或线程 → 底部固定输入区。
- 输入框用 `el-input type="textarea"` + `:autosize`（2–4 行）。**Ctrl+Enter 提交，Enter 换行**。占位文案沿用今天的语义并收窄主语：`用一句自然语言描述你要看的数据（Ctrl + Enter 发送）`。
- 用户气泡右对齐、按内容限宽；助手气泡占满主区宽度（Q10）。
- **空态**：一句引导 + 示例问题列表，**点击直接发问**（今天的 `reuseQuestion` 只填入输入框、要用户再按一次提问，对话范式里这一下是多余的）。引导里明确写出「只能问语义视图覆盖的范围」，让「超出可查范围」可以被预期，而不是碰了才知道。
- 示例问题仍走既有的 `GET /api/internal/analytics/examples`，不新增接口。

### 助手气泡的内容面

一轮的产物顺序固定为：**口径解读 → 结果表 → 可折叠 SQL → 元信息行**。

- 解读：`interpretation` 纯文本，原样呈现（今天已是如此）。
- 结果表：`el-table`，列由 `columns` 决定，行由 `rows` 拉链成对象。**本轮不做图表**（后端不返回图表规格）。
- SQL：默认折叠、可展开，`<pre data-testid="sql-block">` 沿用今天的属性，护栏与既有断言不破。
- 元信息行（贴底）：`共 N 行 · 涉及 <views>`，右侧放 `导出 CSV`（沿用 `csv.ts`，UTF-8 BOM 的客户端 Blob 下载）。
- 警示块，与正常回答同样的位置，**五种业务码各自成文案**，不是一句「出错了」：1101 超出可查范围 / 1102 无法生成查询 / 1103 校验拒绝 / 1104 查询超时 / 1105 执行失败。
- 截断提示：`truncated` 为真时渲染「结果超过行数上限，已截断：仅显示前 N 行，并非全量」。
- 免责声明：`disclaimer` 非空时渲染（只有投顾内容才有；纯内部数据查询不带）。
- **伪流式只作用于解读那一段文本**：整包到达后由打字机播放 `interpretation`，表格与 SQL 等文本播完再出现。`typewriter.ts` 从 `apps/customer/src/chat/` 复制一份到 internal（**不**提升进 shared——Q8 的同一条理由），连同它的 spec。
- **加载态**：POST 在途期间，助手气泡先出现，内容只有「正在查询数据…」+ 三点动画。**不得**演「生成查询 / 校验 / 执行 / 解读」的阶段——后端不告知阶段，编造的过程会被员工当成信息。

### 历史查询进抽屉

- 右栏不再注入 `inspector` → `AppShell` 自动渲染两栏。删除 `useInspector()` 的调用与右栏相关模板。
- 入口：`AppShell` 的 `topbar-right` 插槽，一个「历史查询」按钮 + 页头的「清空对话」。
- 抽屉**一个态**：列表项显示问题、状态、时间、返回行数、截断标记、错误码；SQL 在行内折叠展开；「再问一次」把问题送回输入框（不自动发送）并关闭抽屉。
- 抽屉脚注写明「留痕不存结果集」——这句话从 `AnalyticsHistoryDetail.vue` 搬过来。
- 分页沿用 `PaginationBar` + `usePagination`（ADR-0024），每次打开抽屉从第一页重取（与客服的历史抽屉同口径）。
- `AnalyticsHistoryDetail.vue` 随之折叠掉；`analyticsHistoryRail.spec.ts` **改写**成抽屉的测试（它的前提「证明这张卡在第三栏」已不存在，不是打补丁）。
- **「再问一次」带着当前上下文**，这是 Q3(b)「整个登录会话是一段对话」的直接推论，也是它与「先清空再问」的分工。历史记录原属的那段上下文结构上已经不存在（Redis 键按 `{namespace}:{员工}:{会话标识}` 分，原标识随那次登录结束），所以「恢复它当年的上下文」做不到。

## Testing Decisions

不新增测试 seam，沿用既有 vitest 组件挂载 + 后端 HTTP 测试模式。口径沿用 `frontend-rebuild` Q8：**只测合规呈现面与权限门控**，不逐页复制模板化 spec。

### 后端（Seam 1 — HTTP 层）

- 同一次登录的两次提问落在同一个记忆键上：第二次带上「那上个季度呢」，断言它进了上下文（沿用 `test_short_term_memory.py` 的手法）。
- 请求体**显式**带 `session_id` 时仍然覆盖凭证——这是「清空对话」的机制前提，必须钉住。
- 缺省时仍能正常作答（不因缺 `session_id` 报错）。
- 既有的护栏测试 3 全数保持通过（写操作拒绝、越权取不到基础表、提示词注入不改行级范围、响应不含身份证号 / 手机号 / 银行卡号、截断标记、业务码）。

### 前端（Seam 2 — Vue 组件挂载）

- **线程累积**：连问两次后，界面上同时看得见两轮的问答（这是本次要修的核心缺陷，必须有断言）。
- **五种业务码各自的文案**都能渲染，不是笼统的错误提示。
- 截断提示在 `truncated` 为真时渲染。
- SQL 默认折叠、可展开；`data-testid="sql-block"` 保留。
- 导出 CSV 可用；元信息行的行数与 `views` 正确。
- **线程经 `sessionStorage` 往返后不变形**（重新挂载后内容一致）。
- **登出清空**：调用登出后线程与 sessionStorage 都被清掉。
- **清空对话**：清掉线程，且下一次请求带上了新的会话标识（断言请求体）。
- **历史查询抽屉**：列记录、SQL 行内展开、「再问一次」把问题送进输入框且抽屉关闭、分页走服务端下一页。
- **两栏形态**：数据分析页不再渲染第三栏（改写后的 `analyticsHistoryRail.spec.ts` 仍挂 `App.vue` 断言这一点）。

`pnpm typecheck` 与 `pnpm test` 收尾必须全绿。

## Out of Scope

- **风控问答的界面与会话语义**（Q4a、Q12a）。它的 `RiskQueryTab.vue` 不动、继续传页面级 UUID；`AnalyticsResultView.vue` 也不动，它原样服务这一页。风控问答要改成对话式，另开一份 spec——它的提问带着筛选上下文（预警等级、时间范围），会话寿命的答案未必与这页相同。
- **`packages/shared` 增加聊天组件**（Q8b）。也**不**把 customer 的 `ChatPage.vue` / `ChatHistoryDrawer.vue` 重构过去——那两处已经有第二份重复 markup，合并是另一件事。
- **为逐字效果新增流式端点**（Q5c）。后端 `chat.py` 的 `_sse_frame` 仍是模块私有，本次不提公共 SSE 模块。
- **系统生成的候选追问**（Q2a）。全仓无先例，要做是从零开始的另一项能力。
- **下钻式追问**（Q2a）：点结果表里的某一行继续问。
- **结果表的图表化**：后端不返回图表规格，本 slice 只有表格（沿袭 `data-analysis-agent` 的既有排除）。
- **给留痕表补 `session_id` 列**：零后端改动之外的边界，见 Further Notes。
- **暗色模式、移动端适配**（沿袭 `frontend-rebuild`）。
- **客户侧任何改动**：本次不动 `apps/customer`。

## Further Notes

- **未新增 ADR 的判定**：三条门槛逐条不成立——①「后端 `session_id` 缺省取凭证」是一行的改动、极易反转；②它并不意外，`backend/app/api/analytics.py:30-31` 早已写下「身份取自登录凭证，不取自问题文本」，会话标识同理；③备选（前端解 JWT / 前端自持 UUID）各自的代价（破「不解析凭证」的纪律 / 破 Q3(b) 要买的保证）是明确的次优，没有到「替换要花一个季度」的量级。**因此记在这里而不立文件。**
- **一处已知不一致，是决定不是疏漏**：改完之后，数据分析的会话活到登录结束，风控问答的会话仍是页面级。两条路共用同一份 `AnalyticsQueryRequest`，会话语义却不同。这是 Q12(a)「只动数据分析」的直接结果——理由是不在划下边界的同一次改动里破例，且风控问答的会话寿命该由它自己的 spec 决定。后来读者若想统一，先回答「风控问答的一轮对话该活多久」。
- **一处真实缺口，本次只记录不修**：`biz_analytics_query_audit` 没有 `session_id` 列（只有 `employee_id / question / generated_sql / status / row_count / truncated / error_code / create_time`），所以留痕无法按会话聚合——「这次会话我一共问了哪些」在留痕里查不到。会话改走凭证后这不影响功能，但它是 Q3(b) 留下的缺口：会话由 Redis 短期记忆承载、30 分钟 TTL 一过就无迹可寻，而留痕里也没有能把它捞回来的键。
- **一处词条的措辞分歧**：`CONTEXT.md` 的 **会话** 定义是「一次登录后的连续对话过程」，但结构上记忆是按「员工 + 会话标识」**分 Agent 命名空间**的（`analytics:` 与 `risk_query:`）——同一次登录里，数据分析与风控问答各是一个独立的上下文，也就是两个会话。本 slice 按「一个 Agent 一次登录一个会话」写入词条。若你认为该保持「一次登录一个会话」的笼统说法，改动只有一句话。
- **`CONTEXT.md` 的改动**：只动 **会话** 词条，补一句「丢弃当前上下文不结束会话，唯一会结束会话的事仍是重新登录」，并把定义收窄为「一个 Agent 在一次登录内的连续对话过程」。**不新增词条**。
- **`docs/roadmap.md` 的改动**：`### 收尾` 的「前端从零重做」一行之后补一条指向本 spec。
- **可复用的既有资产**（实现时主动保留，不要顺手重造）：`csv.ts`、`usePagination` + `PaginationBar`（ADR-0024）、`errorMessage`（`apps/internal/src/format.ts`）、`apps/customer/src/chat/typewriter.ts` 与其 spec（复制，不提升）、`packages/shared` 的 `AppShell`（其两栏 / 三栏由插槽存在与否自动决定）。
- **评分表里「安全事故（SQL 注入、无权限校验）-10」仍然对着这条链**：本 slice 只改呈现与上下文，**不碰**查询生成、校验、执行与语义视图。任何让模型的输出多走一步弯路进的改动都要停下来——安全性押在「模型看不到基础表」上，不押在提示词上。
