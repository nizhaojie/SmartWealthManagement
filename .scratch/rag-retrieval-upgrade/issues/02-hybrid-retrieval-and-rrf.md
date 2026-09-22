# 02 — 关键词臂升级为 BM25 一等召回臂，向量 + 关键词 RRF 融合

**What to build:** 关键词检索从「向量超时后的降级路径」升级为正常路径上与向量并行的召回臂，两路各出 20 条、RRF 融合成候选；兜底判定从「单值比单阈值」改成**分臂判定**。这是本 slice 的核心，也是改动面最大的一份。

**Blocked by:** 无（可与 01 并行；建议 01 先合入，好在包含 `rag_db` 语料的库上验收召回质量）

**Status:** ready-for-agent

- [ ] `backend/pyproject.toml` 的 `[project].dependencies` 增加 `jieba>=0.42.1` 与 `rank_bm25>=0.2.2`
- [ ] `Settings` 新增 `hybrid_recall_top_k`（默认 20）、`rrf_k`（默认 60）；`retrieval_keyword_score_threshold` 沿用设置项名，**量纲换成 BM25**
- [ ] `keyword_search_chunks`（`backend/app/knowledge/service.py:379`）改写：读全部 active 分块 → `jieba.lcut` → `BM25Okapi`（df/avgdl 全语料）→ 查询同分词打分 → `knowledge_type` 只过滤**结果** → 取前 `hybrid_recall_top_k`
- [ ] 退役 `_query_terms`、`_keyword_score`、`_escape_like`、`KEYWORD_SCAN_LIMIT`（bigram 切词是「没有分词器时的替代品」）
- [ ] 新增 RRF 纯函数：`rrf_score = Σ 1/(rrf_k + rank_arm)`，去重键 `(knowledge_id, chunk_index)`；两路都命中 → `source = "hybrid"`、`evidence_score` 取较大值
- [ ] `search_chunks` 正常路径改为「向量臂 ∥ 关键词臂 → RRF → top-20 候选」，两臂并行发起
- [ ] 向量臂超时 / 不可用：不再另起一次关键词检索，直接退回「只用关键词臂的排序」，照旧记 `DEGRADED_VECTOR_TIMEOUT` / `DEGRADED_VECTOR_UNAVAILABLE`
- [ ] `ChunkResult` 新增 `evidence_score`；`source` 的 `Literal` 增 `"hybrid"`
- [ ] `app/agent/graph.py`：`AgentState.retrieval_score` 换成 `retrieval_evidence: dict[str, float]`（vector / keyword / graph）
- [ ] `route_after_retrieve`（`backend/app/agent/graph.py:263`）改为分臂判定：向量余弦 ≥ `retrieval_score_threshold` **或** BM25 ≥ `retrieval_keyword_score_threshold` **或** 有图谱段落
- [ ] `fuse_and_rank` 的 `_dedupe_key`（`backend/app/agent/fusion.py:35`）非图谱分支改为 `("chunk", knowledge_id, chunk_index)`，并保留块的 `evidence_score` 与 `source`
- [ ] `tool_calls` 的 `knowledge_search` / `graphrag_fusion` output 带上 `retrieval_evidence`（原始臂分要能看到）
- [ ] 断言（S2）：两臂都没块达标时**不发起生成**，返回兜底话术
- [ ] 断言（S1）：余弦低于阈值、BM25 高于阈值 → 进入生成
- [ ] 断言（S8）：两臂均未达标、仅图谱有段落 → 进入生成
- [ ] 断言（S5）：向量臂超时 → 仍只用关键词臂作答，且 `biz_degradation_trace` 有一行 `vector_store/timeout`
- [ ] 断言：字面明确的查询（含 `T+1`、`七日年化`、客服电话数字串）目标块出现在结果里
- [ ] 断言：`/api/internal/knowledge/search` 与聊天检索对同一 query 的顺序一致

**注意：** `retrieval_keyword_score_threshold` 的量纲变了（比例 → BM25 分），**本份与 04 必须在同一批合入**；本份的测试一律通过注入的 `Settings` 覆盖该阈值，不依赖默认值。`retrieval_score_threshold`（向量余弦）的量纲不变。

**实现落点：** 改 `backend/app/knowledge/service.py`（`keyword_search_chunks` 重写、`search_chunks` 编排、退役三个辅助函数）、
新增 RRF 纯函数（放 `backend/app/knowledge/service.py` 或新的 `backend/app/knowledge/hybrid.py`——后者更利于纯函数单测）、
改 `backend/app/agent/graph.py`（`retrieve_node` / `graph_augment_node` / `route_after_retrieve` / `AgentState`）、
改 `backend/app/agent/fusion.py`（去重键与字段保留）、
改 `backend/app/settings.py` 与 `backend/.env.example`（新增设置项；阈值注释里「命中字词占比」的说法已不对）、
测试 `backend/tests/test_hybrid_retrieval.py`（新增）+ 改写 `backend/tests/test_customer_service_agent.py:131` 与 `backend/tests/test_degradation_paths.py:391`。

### 几处要写下来的决定

**RRF 分不进 `ChunkResult.score`。** `score` 的语义仍是「最终排序分」（今天就是 `fuse_and_rank` 写出的加权和）；RRF 只产生候选顺序，重排再把它写成 0~1 的相关性、或（跳过重排时）写成归一化 RRF。三条召回的量纲混在一起是这套设计最容易失控的地方，因此用 `evidence_score` 单独承载臂内原始分（见 spec 的字段表）。

**降级路径的形态变了，但留痕不变。** 关键词臂本来就在跑，「向量超时」从此只是少了一路召回。`biz_degradation_trace` 的写入点与原因码都不动——统计口径不受影响。

**`keyword_search_chunks` 是回放模式也会走的路径。** `search_chunks` 在 `demo_replay` 下对非预置问题调它；改成 BM25 后仍是本地、确定性运行（ADR-0008 不被违反），但回放测试要重跑确认。
