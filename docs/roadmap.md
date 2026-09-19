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

四个 Agent 分别落在 1、5、6、8；四张 ECharts 图分别落在 4（两张）、6、7。

横切 slice（不占串行链上的位置，可随时插入）：`frontend-rebuild` —— 按 `02-企业浅色.html` 从 0 重写两个前端（三栏内部工作台 / 两栏客户应用），取代 `frontend-restyle`。它不依赖任何未完成的后端能力，拆为三份 issue：shared 地基 → customer 应用 → internal 应用。`frontend-rebuild` 未合并前不要动 `apps/*/src`，否则两端会各自漂移。

另一条横切 slice（2026-09-19）：`advisory-plan-visibility` —— 投顾内容的送达面，客户侧「我的方案」页 + 顾问侧回看已放行内容。它显式推翻 `frontend-rebuild` 的 Q17（「客户侧不新增我的方案页」），理由见该 spec 的 Further Notes。拆为三份 issue：客户侧接口 → 客户侧页面 → 顾问侧回看（第三份不依赖前两份，可并行）。

每份 spec 已拆成 ticket，存于 `.scratch/<slug>/issues/`，共 43 个。依赖是一条串行链：每份 spec 的第一个 ticket 被上一份 spec 的最后一个 ticket 阻塞，spec 内部亦为顺序推进。唯一的例外是 `foundation-and-customer-service-slice #07`（共享包边界检查），它只依赖 #01，可提前做。

**当前 frontier**：`foundation-and-customer-service-slice #01 — 工程骨架与健康检查贯通`（无前置）。

六条护栏测试（ADR-0009）分布：

| 护栏 | 所在 ticket |
|---|---|
| 1 适当性硬过滤 | `customer-profiling-and-suitability #03` |
| 2 身份域隔离 | `foundation-and-customer-service-slice #03` |
| 3 只许只读查询 | `data-analysis-agent #02` |
| 4 产品列表不按收益率排序 | `product-screening-and-customer-assets #01` |
| 5 未审核内容不可送达 | `advisory-agent-and-review-flow #03` |
| 6 shared 不含业务语义 | `foundation-and-customer-service-slice #07` |

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
- [ ] 答辩材料：PPT、API 文档、数据库文档、架构说明
- [ ] 会议纪要补齐（评分表 -5，成本近零）

## 待办的登记项

- [ ] Gitea remote 尚未确定，确定后 `git remote add origin ...`
- [ ] `backend/.env` 填入真实 key 后，把两个 provider 从 `fake` 改为 `openai_compatible`
- [ ] `EMBEDDING_DIMENSION=1024` 必须在建 Milvus 集合前确认，写入后不可改
