# 06 — 回放模式与预置演示场景

**What to build:** 一个环境变量开启回放模式后，预置的问答走确定性回放，完全不依赖模型服务与向量库是否健康。覆盖七类演示场景，每条都产出结构完整、引用合法的响应。

这是「项目无法启动」那条最重扣分项的对冲。它应该在答辩前很久就可用，而不是前一天晚上才想起来——赶进度时回放数据看起来总像是可以放到最后的事（ADR-0008）。

**Blocked by:** 05 — 降级路径全覆盖

**Status:** implemented

- [x] 由环境变量控制开启，日常开发保持关闭
- [x] **开启后不发起任何外部调用**
- [x] 覆盖七类场景：客服问答带引用、产品筛选、画像与适当性、数据查询、投顾方案与审核、图谱多跳、风控预警分级
- [x] **回放输出结构完整、引用合法**——敷衍的假数据在演示时会露馅
- [x] 同一问题的回放结果确定性可复现
- [x] 回放数据与真实链路的响应结构一致，前端无需区分
- [x] 兼作集成测试的夹具

## 落地要点

- **开关与入口**：`settings.demo_replay`（`DEMO_REPLAY` 环境变量，缺省 false）；
  `pnpm demo` 一键启动（= `DEMO_REPLAY=1` 的后端 + 客户端 + 内部端三个前端）。
- **拦截点全在既有缝上，真实管线照走**：检索、融合、引用校验、留痕、SSE 不变，
  只有「叶子」来自预置数据——
  - 模型：`llm.provider.generate_grounded_answer / generate_chitchat_reply`，
    预置问题返回预写回答，未命中走 fake provider 同款确定性拼装；
  - 查询生成与解读：`analytics.llm.generate_query / interpretation`，预置 SQL +
    预写解读，未命中回退示例精确命中 / 口径模板；
  - 向量检索：`knowledge.service.search_chunks` 预置问题返回钉住的分块（内容
    逐字摘自 `faq_seed.md`，分数固定递减），未命中直接走 MySQL 关键词路径，
    连「先试一下向量库」都不发生；
  - 图谱增强：`agent.graph.graph_augment_node` 预置问题返回预写 GraphPassage，
    未命中按「实体未命中」处理（与真实链路同构，融合按加法进行）；
  - 关系图视图：`graph_view.customer_graph_from_db` 从 MySQL 投影组装同一张图，
    行业权重与同步投影共用 `sync.product_industry_weights` 一条查询，任何客户
    都能画、数字与资产页天然一致；
  - Redis：`redis_client()` 返回进程级单例 `InMemoryCache`（`app.replay.local_cache`，
    只实现仓库用到的 9 个方法，TTL 惰性过期）——登录会话、短期记忆、画像缓存、
    问卷草稿照常工作；
  - 事件总线：`NullMirrorPublisher` 丢弃出站镜像，进程内订阅分发照常
    （ADR-0013），跨 Agent 协作演示不受影响。
- **明确拒绝的入口**（会外呼或与回放取数路径冲突，演示误触给业务 400 而不是
  悬着的外呼/500）：图谱重建、知识库上传、知识库下架。
- **确定性**：预置分块分数固定且递减 → 融合（加法，图谱段落 0.4 低于向量分）
  后顺序确定 → 预写回答的 `[N]` 角标与 `cited` 一一对应，`build_citations`
  校验后成为可点角标。数据查询的预写解读只描述口径、不写死行数——统计结果随
  种子数据变，表格里的实时数字才是权威。
- **兼容作测试夹具**：`tests/test_replay_demo_scenarios.py`（13 例）走 HTTP 层
  把七类场景全部跑通，并用桩堵死 `_request_chat`、`embed_texts`、
  `vector_store.get_client`、`object_store.get_client`、`neo4j.Driver.session`，
  Redis 注入 `InMemoryCache`——任何一处发起外部调用当场失败。场景数据落在
  幂等插入的专用客户 `replaydemo1` 上，teardown 按外键序清空，不改写种子客户
  （它们的风险等级被风控/适当性用例精确断言）。纯函数测试锁定预置数据一致性：
  分块内容逐字存在于 FAQ 种子、引用序号合法、预置 SQL 通过校验层。

## 已知取舍

- 预置分块借 `knowledge_id=910001+`：真实文档 id 恒为正、图谱段落用 -1，演示
  前端只用标题与段落路径渲染角标、从不按 id 反查文档（ChatPage.vue 已核）。
- 未命中预置的客服问题在回放模式走 MySQL 关键词路径、不计降级留痕：这是设计性
  绕开而非依赖故障，「降级留痕统计系统多少时间在降级下工作」的口径不受污染。
