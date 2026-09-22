# 03 — 候选集的 LLM 重排（增强，可降级）

**What to build:** 在混合召回（02）之后、图谱融合之前，用一次模型调用把候选重排；重排失败静默退回 RRF 序，并且**不得把已达标的块挤出最终上下文**。

**Blocked by:** 02（重排的输入是 RRF 去重后的候选，需要 `evidence_score` 与 `source` 字段就位）

**Status:** implemented

- [x] 新增 `backend/app/knowledge/rerank.py`：`rerank_chunks(query, chunks, settings)` 返回重排后的候选（保持 `ChunkResult` 形状）
- [x] 重排专用 system prompt：只排序、只输出 JSON、不做判断；输出形如 `{"ranking": [{"index": 3, "score": 0.91}, ...]}`
- [x] `Settings` 新增 `rerank_enabled`（默认 `True`）与 `rerank_timeout_seconds`（默认 `5.0`）
- [x] `chat_completion`（`backend/app/llm/provider.py:184`）增加可选参数：`timeout`、`max_retries`、是否启用备用配置；重排走**单次调用 + `rerank_timeout_seconds` 超时 + 不用备用配置**
- [x] 跳过条件（恒等保序、不发调用）：`rerank_enabled=False`、`resolved_llm_provider == "fake"`、`demo_replay=True`
- [x] 调用超时 / 失败：退回 RRF 序，`degradation.record(dependency=DEPENDENCY_RERANK, reason=timeout|unavailable)`
- [x] `backend/app/degradation.py` 新增 `DEPENDENCY_RERANK = "rerank"`
- [x] 重排结果组装**保底（Q18）**：已达标的块不因重排被挤出上下文——达标块保底占位，未达标块按重排顺序补足名额
- [x] 重排后写 `score`：成功写模型给的相关性（0~1）；跳过 / 降级写**归一化 RRF**（本次候选最高记 1.0，其余按比例，保持单调不增）
- [x] `app/agent/graph.py` 的 `retrieve_node`：`search_chunks(...)` → `rerank_chunks(...)`（**不要把重排放进 `search_chunks`**，见下）
- [x] `app/api/knowledge.py` 的 `/search` 同样显式调用一次重排，保证内部检索接口与聊天看到同一排名
- [x] 断言：重排把达标块排到 top-k 之外时，它仍在最终上下文里
- [x] 断言：`fake` provider 下 `rerank_enabled=True` 时顺序等于 RRF 序，且没有发起 HTTP 请求
- [x] 断言：重排超时 → 顺序退回 RRF 序，`biz_degradation_trace` 有 `rerank/timeout` 一行，且回答照常产出
- [x] 断言：回放模式下结果与改动前一致（S6）

**注意：** **不能把重排塞进 `search_chunks`**——那会形成 `knowledge.service → knowledge.rerank → llm.provider → knowledge.service` 的模块加载环（`llm.provider` 已经 import 了 `knowledge.service`）。重排由调用方（`app/agent/graph.py` 与 `app/api/knowledge.py`）显式串联，`knowledge.service` 不 import `rerank`。

**实现落点：** 新增 `backend/app/knowledge/rerank.py`、
改 `backend/app/llm/provider.py`（`chat_completion` 加可选参数；不改变主链路默认行为）、
改 `backend/app/settings.py` 与 `backend/.env.example`、
改 `backend/app/degradation.py`、
改 `backend/app/agent/graph.py`（`retrieve_node` 加一次重排）、
改 `backend/app/api/knowledge.py`（`/search` 加一次重排）、
测试 `backend/tests/test_rerank.py`（新增）。

### 几处要写下来的决定

**重排的预算独立于主链路。** 主链路是「30s 超时 × (1+3 次重试) 再切备用配置」，那是为「回答必须尽量产出」设计的。检索链路上套这套会把 2s 的向量检索变成 30s+，因此重排单次、短超时、不切备用。备用配置的语义是「主模型不可用时给兜底回答」，不是「重排要更稳」。

**保底占位是对的，因为「该不该作答」不能由一次增强决定。** 若允许重排把达标块全部挤掉，就会出现「分臂判定说有依据、送进模型的上下文里却一个达标块都没有」。这与 Q9「重排只排序」的原则冲突，所以保底不是补丁而是这条原则的实现。

## 落地要点

- **跳过不记降级留痕，与 ADR-0022 决定 3 的措辞冲突，已在 ADR 里补记原因。** ADR 原文把「关闭 / fake / 回放」与「超时 / 失败」并列成「都记一条 `rerank` 降级留痕」，但那三条是「按配置本来就不调用」，记了会让每一次 fake / 回放响应都变成降级响应（`ChatTurnResult.degraded` 直接反查 `biz_degradation_trace`），统计口径当场失效。本份的 issue 与 spec 的「Implementation Decisions」都把 `degradation.record` 只挂在超时 / 失败那一条上，实现按后者。
- **「达标块」的判据按来源臂各自的阈值**：`vector` 用 `retrieval_score_threshold`、`keyword` 用 `retrieval_keyword_score_threshold`；`hybrid` 块的 `evidence_score` 是两路取大、事后分不清属于哪条臂的量纲，因此按两臂中**较松**的一条判（宁可多占一格，也不让可能达标的分块被挤掉）。这条写进了 ADR-0022 决定 5。
- **最终条数取 `AgentConfig.retrieval_top_k`（默认 5），不是新加一个 `Settings` 项。** spec Q17 的散文说「全部进 Settings」，但这条早就以 `AgentConfig.retrieval_top_k` 存在于 Agent 定义里（ADR-0007），此前一直没被用上；重排取货正是它的用途，再在 `Settings` 里放一份会变成两个真相。`rerank_chunks(..., top_k=)` 由调用方传入：聊天传 `retrieval_top_k`，内部检索接口传请求里的 `top_k`。
- **内部检索接口的 `top_k` 语义变了**：它现在是「重排后的最终条数」，候选池固定按 `hybrid_recall_top_k` 取（否则重排没得选，<=5 条里也排不出名次）。`test_hybrid_retrieval.py` 的「接口与聊天同序」断言相应改成按 `retrieval_top_k` 比。
- **重排成功但模型漏排了某条候选时，那条记 `score=0.0` 并沉到尾部。** 成功路径上 `score` 保持「模型相关性」一种量纲；沿用归一化 RRF 会让漏排的块在 `fuse_and_rank` 的加权和里反超模型真正排过的块（0.94~1.0 的量级远高于模型给的相关性）。
- **臂内证据集在重排这一步要原样带过去。** `RetrievedChunks.evidence` 是实例属性，`list(chunks)` 之后就丢了——丢了会退回「从融合结果反推」，把 hybrid 块里 BM25 的量级记进向量臂（无关问题的 BM25 也能到个位数，而余弦阈值是 0.55），于是向量臂凭空达标、该兜底的答了。取证据这件事收拢成 `hybrid.carried_evidence`，`rerank` 与 `agent.graph.build_retrieval_evidence` 共用一份实现。
- **测试侧的两处跟改**：`test_knowledge.py` 的夹具补了 `llm_api_key=""`（内部检索接口现在会串一次模型调用，测试不该外呼）；`test_hybrid_retrieval.py` 的同序断言改成比 `retrieval_top_k`。
