# 02 — 关键词臂升级为 BM25 一等召回臂，向量 + 关键词 RRF 融合

**What to build:** 关键词检索从「向量超时后的降级路径」升级为正常路径上与向量并行的召回臂，两路各出 20 条、RRF 融合成候选；兜底判定从「单值比单阈值」改成**分臂判定**。这是本 slice 的核心，也是改动面最大的一份。

**Blocked by:** 无（可与 01 并行；建议 01 先合入，好在包含 `rag_db` 语料的库上验收召回质量）

**Status:** implemented

- [x] `backend/pyproject.toml` 的 `[project].dependencies` 增加 `jieba>=0.42.1` 与 `rank_bm25>=0.2.2`
- [x] `Settings` 新增 `hybrid_recall_top_k`（默认 20）、`rrf_k`（默认 60）；`retrieval_keyword_score_threshold` 沿用设置项名，**量纲换成 BM25**
- [x] `keyword_search_chunks`（`backend/app/knowledge/service.py:379`）改写：读全部 active 分块 → `jieba.lcut` → `BM25Okapi`（df/avgdl 全语料）→ 查询同分词打分 → `knowledge_type` 只过滤**结果** → 取前 `hybrid_recall_top_k`
- [x] 退役 `_query_terms`、`_keyword_score`、`_escape_like`、`KEYWORD_SCAN_LIMIT`（bigram 切词是「没有分词器时的替代品」）
- [x] 新增 RRF 纯函数：`rrf_score = Σ 1/(rrf_k + rank_arm)`，去重键 `(knowledge_id, chunk_index)`；两路都命中 → `source = "hybrid"`、`evidence_score` 取较大值
- [x] `search_chunks` 正常路径改为「向量臂 ∥ 关键词臂 → RRF → top-20 候选」，两臂并行发起
- [x] 向量臂超时 / 不可用：不再另起一次关键词检索，直接退回「只用关键词臂的排序」，照旧记 `DEGRADED_VECTOR_TIMEOUT` / `DEGRADED_VECTOR_UNAVAILABLE`
- [x] `ChunkResult` 新增 `evidence_score`；`source` 的 `Literal` 增 `"hybrid"`
- [x] `app/agent/graph.py`：`AgentState.retrieval_score` 换成 `retrieval_evidence: dict[str, float]`（vector / keyword / graph）
- [x] `route_after_retrieve`（`backend/app/agent/graph.py:263`）改为分臂判定：向量余弦 ≥ `retrieval_score_threshold` **或** BM25 ≥ `retrieval_keyword_score_threshold` **或** 有图谱段落
- [x] `fuse_and_rank` 的 `_dedupe_key`（`backend/app/agent/fusion.py:35`）非图谱分支改为 `("chunk", knowledge_id, chunk_index)`，并保留块的 `evidence_score` 与 `source`
- [x] `tool_calls` 的 `knowledge_search` / `graphrag_fusion` output 带上 `retrieval_evidence`（原始臂分要能看到）
- [x] 断言（S2）：两臂都没块达标时**不发起生成**，返回兜底话术
- [x] 断言（S1）：余弦低于阈值、BM25 高于阈值 → 进入生成
- [x] 断言（S8）：两臂均未达标、仅图谱有段落 → 进入生成
- [x] 断言（S5）：向量臂超时 → 仍只用关键词臂作答，且 `biz_degradation_trace` 有一行 `vector_store/timeout`
- [x] 断言：字面明确的查询（含 `T+1`、`七日年化`、客服电话数字串）目标块出现在结果里
- [x] 断言：`/api/internal/knowledge/search` 与聊天检索对同一 query 的顺序一致

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

## 落地要点

- **RRF 纯函数与分词放在新模块 `backend/app/knowledge/hybrid.py`**（`tokenize` + `rrf_fuse`）。它用 `TYPE_CHECKING` 才 import `ChunkResult`：真 import 会形成 `service ↔ hybrid` 的模块加载环。`jieba.setLogLevel(WARNING)` 在模块导入时执行一次，免得冷启动刷构建词典的进度行。
- **`RetrievedChunks`（`list[ChunkResult]` 的子类）承载各臂的最高原始分。** `rrf_fuse` 把 hybrid 块合成一条、`evidence_score` 取两路较大值之后，「向量臂最高多少、关键词臂最高多少」就还原不出来了——从候选里按 `source` 反推，会让 BM25 的量纲冒充余弦（实测：无关问题「阿尔法半人马座…」的关键词臂最高约 3.97，被当成余弦后 ≥ 0.55，系统凭空作答）。因此臂内最高分在**两路还分着**的 `search_chunks` 内算好带出，`build_retrieval_evidence` 优先读它；取最高分这件事本身抽成纯函数 `hybrid.arm_evidence`，service（RRF 之前）与 graph（测试替身给普通 `list` 时的退路）共用同一份实现。
- **`retrieve_node` 按 `hybrid_recall_top_k` 取货。** RRF 去重后的整批候选（≤20）就是交给重排的那一批，最终取几条由 issue 03 的重排 + 保底决定；在本份单独合入时，送进模型的相似度片段会暂时是 20 条。内部检索接口的 `top_k` 仍是它自己的请求参数，不跟着变（所以「接口与聊天同序」那条断言要比前 20 条）。
- **向量臂的超时从提交那一刻起算。** 关键词臂在主线程跑，它的耗时会从向量臂的墙钟预算里扣掉（`remaining = timeout - elapsed`，用光时取 0）——否则「关键词臂慢一点」会顺带把向量臂的容忍度拉长，墙钟超时就不再是墙钟超时。
- **图谱证据分恒为 1.0**（`has_graph_passages` 为真即 1.0），不是「段落分里的最大值」：图谱段落的分本来就恒为 1.0，写成取最大值会让「段落分 ≤ 0」这种不该出现的情况悄悄翻转兜底结论。
- **归一化 RRF 让图谱段落恒定排在相似度候选之后。** RRF 归一化是「最高记 1.0、其余按比例」，而 `1/(rrf_k + rank)` 随位次变化很慢，全部候选都落在 0.94~1.0 附近；乘上 `graphrag_vector_weight`（0.6）后恒高于图谱段落的 `graph_weight × 1.0`（0.4）。图谱段落因此恒定是「附加」而不是「优先」——它仍在上下文里、仍可被引用，但不再保证进前三个角标。`test_customer_service_agent_graphrag.py` 里那条断言相应改成「图谱段落进入上下文与留痕」（`retrieval_snippets` 里有 `source == "graph"`、`retrieval_evidence["graph"] == 1.0`），不再是「引用里出现《知识图谱》」。
- **默认关键词阈值仍是占位的 0.35**（量纲已换成 BM25 分），必须由 04 的校准脚本写回。在它写回之前，BM25 一侧几乎必然达标，系统会「答不该答的」；这是 issue 明确认下的代价（02 与 04 同批合入）。
- **既有用例里需要显式注入 `retrieval_keyword_score_threshold`**：`test_customer_service_agent.py`、`test_chat_stream.py`、`test_replay_demo_scenarios.py`、`test_customer_service_agent_graphrag.py` 的夹具都注入 `10.0`（实测：无关问题共享「系统」这类高频词时 BM25 ≈ 4，逐字命中一块 ≈ 40，10 分得开）。注入的位置都写了「默认值等 04 校准」的注释，04 落地后可以评估是否撤掉。
- **`Settings` 另加 `jieba_user_dict_path`（默认空）**：spec 的「预留可选用户词典路径」落成一个配置项，文件不存在则跳过（`hybrid._load_user_dict` 用 `lru_cache` 保证只加载一次）。本 slice 不提供词表。
- **`documentation`**：`docs/system-architecture.md` 里描述 `retrieval_score` 的那一行已改成「分臂判定 + 混合召回」，否则文档会指着一个已不存在的字段。
