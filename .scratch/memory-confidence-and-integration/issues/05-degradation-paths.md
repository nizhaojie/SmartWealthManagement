# 05 — 降级路径全覆盖

**What to build:** 任何一个外部依赖抖动时，系统给出降级后的服务而不是把错误抛给用户：模型调用失败就退避重试、切备用、最后返回预设兜底；向量检索超时降为关键词检索；图谱超时跳过增强；缓存不可用直连数据库；事件总线不可用则核心链路照常。每一次降级都留痕，于是事后能知道系统实际上有多少时间在降级状态下工作。

**Blocked by:** 04 — Agent 间事件协作

**Status:** implemented

- [x] 模型调用失败：按退避策略重试，仍失败切换备用配置，再失败返回预设兜底回答
- [x] 向量检索超时：降级为关键词检索，仍返回可用结果
- [x] 图谱查询超时：跳过增强，只用向量结果（与 knowledge-graph-and-graphrag #03 的降级一致，此处补齐其余入口）
- [x] 缓存不可用：直连数据库，恢复后自动回填
- [x] 事件总线不可用：记录日志，核心链路继续
- [x] **每一处降级都在留痕中记录**，可统计降级发生的频次
- [x] 降级后的回答在前端正常渲染，不因缺少引用而报错
- [x] 各依赖的超时阈值可配置
- [x] 每个请求的追踪标识贯穿全链路，出现在响应与所有相关日志行中
- [x] 各 Agent 的响应时间有统计

## 落地要点

- **降级留痕**：`biz_degradation_trace`（依赖 / 原因 / Agent / 追踪标识 / 详情），
  `app.degradation.record` 走**自己的会话**（不共用调用方事务）且吞掉写入异常；
  `GET /api/internal/traces/degradations` 给出总数、按依赖、按原因三组统计。
- **模型调用**：`app.llm.provider.chat_completion` 按 `llm_max_retries` 指数退避
  （间隔 1s / 2s / 4s，总调用 1 + 重试次数 = 4 次），仍失败切 `llm_backup_*`，
  再失败抛业务错误码；客服 Agent 捕获后返回 `model_failure_answer` 预设兜底并留痕。
- **向量检索**：`app.knowledge.service.search_chunks` 用线程池给墙钟超时
  （`vector_search_timeout_seconds`，默认 2s），超时或不可用时改查 MySQL 分块镜像
  `fin_knowledge_chunk` 的 LIKE 关键词检索（见 ADR-0014）。
- **图谱**：GraphRAG 原有降级不变（超时阈值默认 3s），并在客服 `graph_augment_node`
  里把属于依赖抖动的原因（超时 / 不可达 / 重建中无旧图）计入降级留痕——实体未命中
  是正常结果，不计数。关系图入口 `graph_view.customer_graph_degraded` 补了同样的
  超时保护：超时/不可用返回空图 + `degraded` 标记，但输入非法（如非正数
  customer_id）仍照常 400，不因降级被吞掉。
- **缓存**：画像 Cache-Aside 在缓存不可用时直连数据库、恢复后自动回填；短期记忆
  读不到就退化成无上下文的单轮，写不进去只记日志。Redis 客户端补了连接/读写超时。
- **事件总线**：`publish_safely` 照旧吞异常，调用方（客服、风控）在返回 False 时
  补一条降级留痕。
- **追踪与统计**：聊天响应与 SSE done 帧带 `trace_id` 与 `degraded`；
  `GET /api/internal/traces/agent-response-times` 按 Agent 给出次数/平均/最快/最慢。

测试：`backend/tests/test_degradation_paths.py`（18 例，HTTP 层 + 纯函数）、
`apps/customer/src/chat/ChatPage.spec.ts` 的降级回答渲染用例。
「图谱不可用时返回基于向量的结果」由 ticket 03 的 `test_knowledge_graph_graphrag.py`
与 `test_agent_fusion.py` 覆盖，此处不重复。

术语「降级 / 降级留痕」已进 `CONTEXT.md` 词汇表。
