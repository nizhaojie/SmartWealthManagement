# 03 — 候选集的 LLM 重排（增强，可降级）

**What to build:** 在混合召回（02）之后、图谱融合之前，用一次模型调用把候选重排；重排失败静默退回 RRF 序，并且**不得把已达标的块挤出最终上下文**。

**Blocked by:** 02（重排的输入是 RRF 去重后的候选，需要 `evidence_score` 与 `source` 字段就位）

**Status:** ready-for-agent

- [ ] 新增 `backend/app/knowledge/rerank.py`：`rerank_chunks(query, chunks, settings)` 返回重排后的候选（保持 `ChunkResult` 形状）
- [ ] 重排专用 system prompt：只排序、只输出 JSON、不做判断；输出形如 `{"ranking": [{"index": 3, "score": 0.91}, ...]}`
- [ ] `Settings` 新增 `rerank_enabled`（默认 `True`）与 `rerank_timeout_seconds`（默认 `5.0`）
- [ ] `chat_completion`（`backend/app/llm/provider.py:184`）增加可选参数：`timeout`、`max_retries`、是否启用备用配置；重排走**单次调用 + `rerank_timeout_seconds` 超时 + 不用备用配置**
- [ ] 跳过条件（恒等保序、不发调用）：`rerank_enabled=False`、`resolved_llm_provider == "fake"`、`demo_replay=True`
- [ ] 调用超时 / 失败：退回 RRF 序，`degradation.record(dependency=DEPENDENCY_RERANK, reason=timeout|unavailable)`
- [ ] `backend/app/degradation.py` 新增 `DEPENDENCY_RERANK = "rerank"`
- [ ] 重排结果组装**保底（Q18）**：已达标的块不因重排被挤出上下文——达标块保底占位，未达标块按重排顺序补足名额
- [ ] 重排后写 `score`：成功写模型给的相关性（0~1）；跳过 / 降级写**归一化 RRF**（本次候选最高记 1.0，其余按比例，保持单调不增）
- [ ] `app/agent/graph.py` 的 `retrieve_node`：`search_chunks(...)` → `rerank_chunks(...)`（**不要把重排放进 `search_chunks`**，见下）
- [ ] `app/api/knowledge.py` 的 `/search` 同样显式调用一次重排，保证内部检索接口与聊天看到同一排名
- [ ] 断言：重排把达标块排到 top-k 之外时，它仍在最终上下文里
- [ ] 断言：`fake` provider 下 `rerank_enabled=True` 时顺序等于 RRF 序，且没有发起 HTTP 请求
- [ ] 断言：重排超时 → 顺序退回 RRF 序，`biz_degradation_trace` 有 `rerank/timeout` 一行，且回答照常产出
- [ ] 断言：回放模式下结果与改动前一致（S6）

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
