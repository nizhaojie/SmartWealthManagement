# 混合检索、重排与 FAQ 按对拆分

Status: ready-for-agent

前置：`foundation-and-customer-service-slice`（知识入库 + 检索 + 强制引用）、`knowledge-graph-and-graphrag`（融合排序与图谱增强）、`memory-confidence-and-integration`（降级路径与回放模式）。

**本 slice 修改已实现的既有决定**（不是新增，是改动，实现时先读这几处）：

| 被改的既有决定 | 改动内容 |
|---|---|
| ADR-0014「关键词检索只在向量超时 / 不可用时使用，不参与正常路径的排序」 | 关键词升级为**一等召回臂**，正常路径与向量并行召回；降级路径复用同一条 BM25 查询。ADR-0014 随本 slice 修订。 |
| ADR-0014「降级路径的 `ChunkResult.source` 仍标 "vector"」 | 该描述与代码不符（`keyword_search_chunks` 实标 `"keyword"`），一并修正；`source` 新增 `"hybrid"` 取值。 |
| `retrieval_score_threshold` / `retrieval_keyword_score_threshold` 由经验值给定、判定为「单值比单阈值」 | 两条阈值改由 golden 集校准产出；判定改为**分臂判定**（Q9）。 |

**明确不改**（实现时容易顺手改掉，列在这里当护栏）：Milvus 仍是向量检索的权威面（ADR-0014 第 2 条）；图谱仍是增强不是依赖（`app/knowledge_graph/graphrag.py` 的模块契约）；「检索不到依据时不作答」；回放模式不发起任何外部调用（ADR-0008）；`KnowledgeType` 仍是 `FAQ / 产品 / 政策` 三值，不新增类型（Q12）。

## Problem Statement

**一、正常路径只有向量一路召回，中文财务问句的字面信号被浪费。**

关键词检索是有的（`backend/app/knowledge/service.py:379` 的 `keyword_search_chunks`），但它的唯一用途是「向量检索超时或不可用时的降级」，正常路径一次都不会碰它（`search_chunks`，同文件 `:430`）。而中文财务问句的判别信号里，有相当一部分是**字面**的：「七日年化」「T+1」「业绩比较基准」「R1 到 R5」「400-XXX-XXXX」。向量对这种短实体、代码、数字串的区分力本来就不如字面匹配，而分类别（`knowledge_type`）、同义词密集的语料又会让余弦把不相干的块拉到一起。一路召回的代价是：**只要向量排序错了，重排与生成都救不回来**——因为正确的块根本不在候选集里。

**二、两条阈值是猜的，而且从没量过与「无关噪声基线」的距离。**

`retrieval_score_threshold = 0.55` 与 `retrieval_keyword_score_threshold = 0.35` 来自注释里的经验值（`backend/.env.example:109-117`、`backend/app/settings.py:99-102`）。阈值自己的注释就写着「真实 embedding 对无关文本的余弦也能到 0.4~0.5」——也就是说，0.55 与噪声基线之间只隔了 0.05，而**这个距离从未被任何数据集量过**。`backend/tests/test_customer_service_agent.py:131` 用一条 `score=0.45` 的假命中把它「钉住」，但那条断言保护的是注释里的数字，不是可回归的口径。没有 golden 集，阈值只能随语料与模型漂移而无声失准。

**三、tab 分隔的 FAQ 语料会被整体切块，问答对被切碎。**

`_parse_txt`（`backend/app/knowledge/parsers.py:39`）把整篇 txt 当一个 Section 再交给 512 token / overlap 64 的滑动窗口。于是 `rag_db/公司信息/高频问答对.txt` 的 39 组 `问题\t答案` 会被切碎：一组问答横跨两个块、一个块里塞着上一组的答案尾巴。检索命中的是片段，引用角标指向的位置也不是完整的一组问答；对 FAQ 这种「一问一答就是最小完整语义单元」的语料，这是错误的切分粒度。同一份 txt 走 markdown 路径时反而正确（`## 问题` 天然成对），说明缺的是 txt 路径上的识别，不是模型能力。

## Solution

**一、混合检索 + RRF + LLM 重排。**

- **两路并行召回**：向量臂（Milvus，维持现状）与关键词臂（`rank_bm25` 的 Okapi BM25，跑在既有的 MySQL 分块镜像上，`fin_knowledge_chunk`）。两条召回各出 top-20。
- **RRF 融合**：`rrf_score = Σ 1/(rrf_k + rank)`，`rrf_k = 60`。RRF 免去「向量分与 BM25 分怎么归一化」这个无底洞——它只用位次，天然跨量纲。
- **LLM 重排**：把 RRF 去重后的候选交给一次模型调用，要它输出「候选序号 + 相关性 0~1」的重排。重排是**增强**：超时、失败、`fake`/回放模式下都静默退回 RRF 序。
- **图谱不变**：候选先与图谱段落做既有的加权和融合（`app/agent/fusion.py`，保留 `graphrag_vector_weight/graph_weight`），图谱段落**不参与重排**——它是查出来的确定事实，不是相似度意义上的「相关性」。

**二、真实 embedding + golden 集校准两条阈值。**

`text-embedding-v3` 已在配置里（`EMBEDDING_PROVIDER` / `EMBEDDING_DIMENSION=1024`），本 slice 用一组 golden 问答集跑回归，把两条阈值从「注释里的经验值」变成「数据集量出来的值」，并把校准脚本固化下来。

**三、FAQ 按对拆分 + `rag_db/` 正式语料入库。**

`_parse_txt` 识别连续的 `问题\t答案` 行，**一组问答一个分块**，`heading_path = [问题]`、`content = 问题\n答案`；非 tab 行按普通文本处理。同批给 `rag_db/` 补一个幂等 seed 脚本，让它作为正式语料入库（Q6）。

## 访谈结论清单（grill-with-docs，2026-09-22）

### 第一轮

| # | 决定 |
|---|---|
| Q1 | **文档先行**：一份 spec（本文件）+ 新增 ADR-0022 + 修订 ADR-0014 + `CONTEXT.md` 加「证据分」，拆 4 份 issue；确认后才动代码。 |
| Q2 | 关键词召回**升级为一等召回臂**（正常路径并行召回、RRF 融合）；既有「向量不可用 → 只用关键词 + 降级留痕」路径保留。 |
| Q3 | rerank 用 **LLM 重排**（复用既有 `chat_completion` 链路），不引入 cross-encoder 本地模型。 |
| Q4 | FAQ 拆分**以内容嗅探（tab）为主、兼容 markdown**；不改 `faq_seed.md`。 |
| Q5 | 校准目标量 = 兜底判定的「证据分」；golden 集放 `backend/tests/fixtures/`；校准走独立脚本；CI 回归用 fake embedding 只钉相对关系。 |
| Q6 | `rag_db/` 认定为**正式知识库语料**，补 seed 脚本入库。 |

### 第二轮

| # | 决定 |
|---|---|
| Q7 | 关键词臂用 **`rank_bm25`（Okapi BM25）+ `jieba`**（新增两个依赖，pip 安装需联网一次）。 |
| Q8 | **RRF 只融「向量 + 关键词」**；结果再与图谱段落做加权和（保留两个权重旋钮）；图谱段落恒定附加、不参与重排；两路都命中的块 `source = "hybrid"`。 |
| Q9 | 兜底判定改**分臂判定**：向量臂最高余弦 ≥ `retrieval_score_threshold` **或** 关键词臂最高 BM25 ≥ `retrieval_keyword_score_threshold` **或** 有图谱段落，即认为有依据。RRF / 重排只决定排序。 |
| Q10 | 召回 top-20（每臂）→ RRF 去重 → LLM 重排 → 取 5；rerank 默认开；`fake` / 回放恒等保序；独立短超时 `rerank_timeout_seconds`（默认 5s）+ 单次不重试；失败静默退回 RRF 序并记 `DEPENDENCY_RERANK`。 |
| Q11 | FAQ 走**纯内容嗅探**（`parse_document` 签名不变）；块 `content = 问题\n答案`、`heading_path = [问题]`；不加「问：/答：」标签。 |
| Q12 | `rag_db/` **不新增知识类型**，写一张显式目录 → 类型映射表；新增幂等 `seed_rag_db.py`。 |
| Q13 | 新增 **ADR-0022**；修订 **ADR-0014**；`CONTEXT.md` 只加「证据分」一条，混合检索 / RRF / rerank 属实现、只进 ADR。 |

### 第三轮

| # | 决定 |
|---|---|
| Q14 | BM25 的 df / avgdl 在**全语料（所有 active 分块）**上统计，`knowledge_type` 只过滤返回结果。 |
| Q15 | BM25 索引**每次查询现建**（读镜像表 → jieba 分词 → `BM25Okapi`），不做进程内缓存、不做持久化。 |
| Q16 | 查询侧与文档侧统一 `jieba.lcut`（精确模式）；过滤纯空白 / 标点 token；不建自定义金融词典，预留可选用户词典路径；依赖 pin 进 `pyproject.toml`。 |
| Q17 | `rrf_k = 60`、`hybrid_recall_top_k = 20`、重排候选数 = RRF 去重后前 20、最终 `retrieval_top_k = 5`，全部进 `Settings`。 |
| Q18 | 重排**不得把已达标的块挤出上下文**：达标的块保底占位，未达标块按重排序补足名额。 |
| Q19 | 边界场景 S1–S8 全部确认（见下表）。 |

**边界场景（Q19）**：

| # | 场景 | 预期 |
|---|---|---|
| S1 | 关键词臂 BM25 达标、向量余弦 0.42 未达标 | 生成，该块 `source="keyword"` |
| S2 | 两臂都没块达标，但 RRF 融合后有块排第一 | **兜底**（RRF 只排序、不改变有无依据） |
| S3 | 两臂各有一块达标，RRF / 重排后关键词块排前 | 生成，引用顺序以融合后为准 |
| S4 | 重排把关键词块提到第一，但向量块证据分更高 | 生成（任一臂达标即可） |
| S5 | Milvus 超时 | 只用 BM25 臂 + 记 `DEGRADED_VECTOR_TIMEOUT`；BM25 达标则生成，否则兜底 |
| S6 | 回放模式 | 不发 embedding、不发 rerank 调用，既有回放测试的确定性结果不变 |
| S7 | `fake` provider | rerank 恒等保序，测试确定性 |
| S8 | 仅图谱实体命中（两臂均未达标） | 生成（图谱段落 1.0 是确定事实，沿用现状） |

## User Stories

### 客户

1. As a 客户, I want to 问到「七日年化」「T+1」「400 客服电话」这类字面明确的问题时能命中正确的问答, so that 我不会因为向量把相近但不相关的块排上来而拿到答非所问的回答
2. As a 客户, I want to 引用角标指向一组完整的问答而不是被切成两半的片段, so that 我点进去看到的依据是完整的
3. As a 客户, I want to 在知识库里确实没有依据时仍然收到「查不到、请转人工」的明确说法, so that 系统不会为了作答而拿低相关片段充数

### 合规负责人

4. As a 合规负责人, I want to 兜底阈值来自一套可回归的数据集而不是注释里的经验值, so that 换 embedding 模型或语料扩容时阈值失准能被测试发现而不是无声漂移
5. As a 合规负责人, I want to 「有无依据」的判定不受重排（一次模型调用）影响, so that 一个增强环节的抖动不会改变「该不该作答」这个合规结论

### 开发者

6. As a 开发者, I want to 关键词臂与降级路径共用同一条 BM25 查询, so that 关键词检索只有一套实现、一套口径
7. As a 开发者, I want to 三条召回（向量 / 关键词 / 图谱）的融合顺序在代码里一处可见, so that 改排序时不必追三处
8. As a 开发者, I want to 新增依赖是两个纯本地库（无运行期网络）, so that 回放与测试仍是离线的确定性运行

## Implementation Decisions

### 依赖与设置项

`backend/pyproject.toml` 的 `[project].dependencies` 增加：

```
"jieba>=0.42.1",
"rank_bm25>=0.2.2",
```

两者都是纯本地库：`jieba` 自带词典（运行期不联网，首次分词会建前缀词典缓存），`rank_bm25` 无外部依赖。**pip 安装需联网一次**，这是本 slice 唯一的环境要求。

`backend/app/settings.py` 新增 / 调整：

| 设置项 | 默认 | 说明 |
|---|---|---|
| `hybrid_recall_top_k` | `20` | 每个召回臂各自返回的候选数（Q17） |
| `rrf_k` | `60` | RRF 平滑常数（Q17） |
| `rerank_enabled` | `True` | 重排开关（Q10） |
| `rerank_timeout_seconds` | `5.0` | 重排单次调用的墙钟超时（Q10） |
| `retrieval_score_threshold` | 由校准写回 | 量纲不变（余弦），取值由 04 产出 |
| `retrieval_keyword_score_threshold` | 由校准写回 | **量纲变了**：从「命中字词占比」变成 BM25 分，取值由 04 产出 |

`retrieval_keyword_score_threshold` 的量纲变化意味着 **02 与 04 必须在同一批内合入**：只合 02 会让默认值对着错误量纲生效。02 的测试一律通过注入的 `Settings` 覆盖该阈值，不依赖默认值；04 负责把两条阈值的校准值写回 `Settings` 与 `backend/.env.example`（连带更新 `.env.example:109-117` 的注释——「命中字词占比」的说法已经不对了）。

### 关键词臂：镜像表上的 BM25

`keyword_search_chunks`（`backend/app/knowledge/service.py:379`）从「LIKE 预筛 + 字词命中占比打分」改写为：

1. 读 `fin_knowledge_chunk` join `fin_knowledge_meta`（`status = 'active'`）的**全部**行，构成语料。
2. 对每条 `content` 做 `jieba.lcut`，构建 `BM25Okapi`（df / avgdl 在**全语料**上算——Q14）。
3. 对查询做同一分词，`get_scores`；按 `knowledge_type` 过滤**结果**（不过滤语料）。
4. 取前 `hybrid_recall_top_k` 条，`source = "keyword"`、`evidence_score = BM25 分`。

`_query_terms` 与 `_keyword_score`（同文件 `:346`、`:371`）连同 `KEYWORD_SCAN_LIMIT` 一并退役——bigram 切词是「没有分词器时的替代品」，现在有 `jieba` 了。`_escape_like` 也随 LIKE 查询一起退役。

**代价同时认下**：每次查询读全表并重新分词。当前语料是百级分块，单次几十毫秒；语料规模上来后若成为瓶颈，再评估 Q15 里被否决的「进程内缓存 + 失效」，且失效必须走数据库版本号而不是进程内事件（多 worker 下进程内事件会漂移）。

### 分词

查询侧与文档侧必须是**同一个分词器、同一种模式**，否则 BM25 的词表对不上：

- 统一 `jieba.lcut(text)`（精确模式）。
- 丢弃纯空白与纯标点 token（它们只贡献噪声 df）。
- **不建自定义金融词典**（Q16）：BM25 对「七日 / 年化 / 收益率」这类切分不敏感；预留一个可选的用户词典路径（配置项指向一个词表文件，不存在则跳过），但本 slice 不提供词表。

### 混合与 RRF

`search_chunks` 的正常路径从「只调向量臂」改为：

```
向量臂 ── top-20 ─┐
                  ├─ RRF 融合（去重）── top-20 候选
关键词臂 ─ top-20 ─┘
```

- **去重键** = `(knowledge_id, chunk_index)`。同一个块被两路同时命中时合并为一条，`source = "hybrid"`，`evidence_score` 取两路中的较大值（判定用）。
- **RRF 分** = `Σ 1/(rrf_k + rank_arm)`，`rank_arm` 从 1 起。它只用于产生候选顺序。
- 向量臂与关键词臂**并行发起**：两臂各自都有自己的墙钟超时，向量臂沿用 `vector_search_timeout_seconds`，关键词臂是本地 MySQL + CPU，不设超时。

**降级路径的形态变化**：原来「向量超时 → 关键词全量兜底」；现在关键词臂本来就在跑，所以向量超时只是**少了一路召回**，结果退回「只用关键词臂的排序」，并照旧记 `DEGRADED_VECTOR_TIMEOUT` / `DEGRADED_VECTOR_UNAVAILABLE`。`_degraded_keyword_results` 因此不再需要单独发起一次关键词检索——它复用已经拿到的关键词臂结果。回放模式的非预置问题仍走关键词臂（本地、确定性，ADR-0008 不受影响）。

### rerank

**位置**：在混合召回之后、图谱融合之前，只在「相似度分块」上做（Q8）。

**调用形态**：一次模型调用，输入是查询 + 带序号的候选文本，输出形如 `{"ranking": [{"index": 3, "score": 0.91}, ...]}`。模型只被要求**排序与打分**，不被要求生成文本。

**降级（三条并存）**：
- `settings.rerank_enabled` 为假 → 跳过；
- `settings.resolved_llm_provider == "fake"` 或 `settings.demo_replay` → 恒等保序（不发调用），保证测试确定性；
- 调用超时 / 失败 → 退回 RRF 序，记 `degradation.record(dependency=DEPENDENCY_RERANK, reason=timeout|unavailable)`。`app/degradation.py` 新增 `DEPENDENCY_RERANK = "rerank"`。

**超时与重试**：复用 `chat_completion`，但**不套用**主链路的重试策略——主链路是 `llm_timeout_seconds`(30s) × (1 + `llm_max_retries`)，把这套搬到检索链上会把 2s 的检索变成 30s+。做法是给 `chat_completion` 增加可选参数（`timeout`、`max_retries`、是否启用备用配置），重排走单次调用、`rerank_timeout_seconds` 超时、不用备用配置。备用配置的语义是「主模型不可用时的兜底回答」，不是「重排要更稳」。

**保底（Q18）**：重排结果按「达标块保底占位 + 未达标块按重排补足」组装，保证已达标的块不会被挤出最终上下文。若不达标的块在重排后排名更高，它排在达标块之前、但仍不挤掉达标块的名额。

**提示词**：`GROUNDED_SYSTEM_PROMPT` 那套「只能依据片段、带编号引用」的约束与重排无关，另立一份重排专用 system prompt（只排序、只输出 JSON、不做判断）。提示词与候选用 `app/llm/provider.py` 现成的 `chat_completion` 发。

### 证据分与兜底判定（Q9）

`app/agent/graph.py` 的 `graph_augment_node` 不再算单一的 `retrieval_score`，改算一个**分臂证据集**：

```
evidence = {
  "vector":  向量臂最高余弦   (无命中则 0.0),
  "keyword": 关键词臂最高 BM25 (无命中则 0.0),
  "graph":   有图谱段落则 1.0, 否则 0.0,
}
```

`route_after_retrieve`（同文件 `:263`）从「比一个数」改为：

```
向量臂达标  := evidence["vector"]  >= retrieval_score_threshold
关键词臂达标 := evidence["keyword"] >= retrieval_keyword_score_threshold
图谱达标    := evidence["graph"] > 0
有依据      := 三者之一
无依据      := 兜底
```

`AgentState` 里的 `retrieval_score: float` 换成 `retrieval_evidence: dict[str, float]`；`tool_calls` 里 `knowledge_search` / `graphrag_fusion` 的 output 一并带上这个字典，供调试留痕与校准复查——**原始臂分不进 `ChunkResult.score`，但要能看到**。

**这一条是本 slice 最需要守住的地方**：它保证「重排与 RRF 只影响排序，不影响该不该作答」。

### `score` / `evidence_score` / `source` 的语义

`ChunkResult` 新增一个字段，三个字段各司其职：

| 字段 | 语义 | 量纲 |
|---|---|---|
| `evidence_score` | 该块在**其来源臂**上的原始分，是分臂判定的输入 | 余弦 / BM25 / 图谱 1.0 |
| `score` | 该块最终的**排序分**（与今天一致：由 `fuse_and_rank` 写出的加权和） | 0~1（重排相关性或归一化 RRF 与图谱分加权） |
| `source` | 命中来源 | `vector` / `keyword` / `hybrid` / `graph` |

`score` 在流水线里被写两次：重排成功时写成模型给的相关性（0~1）；跳过或降级时写成**归一化 RRF**（本次候选里最高 RRF 记 1.0，其余按比例），以保持与图谱分（1.0）同一量纲、且严格单调不增。这样既让 `fuse_and_rank` 的加权和继续成立（两个权重旋钮仍在），也让界面 / 调试留痕里的 `score` 仍是可读的 0~1。

`_dedupe_key`（`app/agent/fusion.py:35`）里非图谱分支的 `("vector", id, index)` 改为 `("chunk", id, index)`——去重身份是「哪个分块」，不是「哪条路径」。

**回放模式**：预置分块的 `evidence_score` 直接取预置的 `score`（预置分同时充当证据分），既有回放断言因此仍然成立。

### 图谱融合里不变的部分

`fuse_and_rank`（`app/agent/fusion.py:43`）的两条既有取舍原样保留：

- **没有图谱段落时原样返回召回结果**，不乘 `vector_weight`（否则图谱的缺席会凭空抬高兜底门槛）。
- **图谱段落 score = 1.0**（`graphrag.py` 的既有决定：关系是确定事实，业务量级不混进置信度）。

本 slice 只增加一件事：融合时保留每块的 `evidence_score` 与 `source`（`dataclasses.replace` 已经能做到）。

### FAQ 按对拆分（Q11）

`_parse_txt`（`backend/app/knowledge/parsers.py:39`）改为逐行扫描：

- 一行含 tab 且**第一个 tab 之前非空** → 一组问答对：`question = 第一个 tab 之前`、`answer = 第一个 tab 之后`（用 `split("\t", 1)`，答案内部再有 tab 不二次切分）。
- 每一组问答对产出**一个 `Section`**：`heading_path = [question]`、`text = question + "\n" + answer`。
- 不含 tab 的行按原样累积到普通缓冲，遇到问答行时先 flush，文件末尾再 flush；普通 Section 的 `heading_path = []`。
- 顺序保持文件原始顺序（问答块与普通块交错时也按出现顺序）。

问答对再经 `_chunk_sections` 走同一条 512/64 切分——一组问答通常远短于 512 token，因此结果就是**一对一块**；只有超长问答才会被二次切分，这是合理兜底而不是常态。

**不做类型感知**：`parse_document` 签名不变、不接收 `knowledge_type`（Q11）。tab 分隔本身是强特征，且嗅探让任何类型的 txt 都能受益。**代价**：一份「用 tab 排版的表格型 txt」会被误判成问答对——这是接受的代价，写进 Further Notes，不为此加一个类型参数。

### `rag_db/` 语料入库（Q12）

新增 `backend/app/knowledge/seed_rag_db.py`（与 `seed_faq.py` 同型）：

- 递归扫描仓库根目录下的 `rag_db/`，收 `.md` 与 `.txt`。
- 目录 → `knowledge_type` 映射表（显式写在脚本里，集中一处）：

| 路径前缀 | `knowledge_type` |
|---|---|
| `金融政策/` | `政策` |
| `公司业务/个人理财产品手册.md` | `产品` |
| 其余 | `FAQ` |

- `source_file` = 相对 `rag_db/` 的 POSIX 路径（如 `公司信息/企业信息.md`），`title` = 文件名（去扩展名）。
- **幂等**：已存在同 `source_file` 且 `status = active` 的文档即跳过——与 `seed_faq` 同一口径。
- 入库走既有的 `ingest_document`，因此 FAQ 按对拆分（本 slice 的第 01 份 issue）与 embedding 自动生效。

**不新增知识类型**（Q12）：`KnowledgeType`（`backend/app/knowledge/schemas.py:6`）与前端选项一个字不改。把「公司信息」归到 `FAQ` 是口径上的一次让步——它表达的是「非产品、非政策的常识性问答」，够用且不牵连 schema。

### 模块摆放与导入环

重排放在**新模块 `backend/app/knowledge/rerank.py`**。它需要 `ChunkResult`（来自 `app.knowledge.service`）与 `chat_completion`（来自 `app.llm.provider`，而后者已经 import 了 `app.knowledge.service`）。

**不能把重排塞进 `search_chunks`**：那会造成 `knowledge.service → knowledge.rerank → llm.provider → knowledge.service` 的模块加载环。正确摆法是**由调用方串起来**：

- `app/agent/graph.py` 的 `retrieve_node`：`search_chunks(...)` → `rerank_chunks(...)`；
- `app/api/knowledge.py` 的 `/search` 同样显式调用一次（内部检索接口看到的排名应与聊天一致）。

`knowledge.service` 不 import `rerank`，环因此不存在。

### 前端

**无前端改动。** 客户端只消费回答与引用角标；内部端的知识检索界面消费的是同一套 `score`（仍是 0~1）与既有字段。`score_threshold` 一栏回报的仍是 `retrieval_score_threshold`（`api/knowledge.py:137`），语义未变。

## Testing Decisions

两个 seam：后端 HTTP 层 + 纯函数 / 确定性回放。

### Seam 1 — 后端 HTTP 层

护栏相关：

- **字面关键词问题能命中对应问答**：用一组「向量容易糊、字面明确」的查询（含 `T+1`、`七日年化`、客服电话数字串）断言目标块在结果里。这是关键词臂存在的理由，必须有一条直接断言。
- **两臂都没块达标时兜底**（S2）：构造「余弦低于向量阈值、BM25 低于关键词阈值」的召回，断言**不发起生成**、返回兜底话术。这条钉住「RRF 只排序、不改变有无依据」。
- **关键词臂单独达标即可作答**（S1）：余弦低于阈值、BM25 高于阈值，断言进入了生成。
- **仅图谱命中仍作答**（S8）：两臂均未达标、图谱有段落，断言进入生成——图谱是增强不是依赖的另一面。
- **重排不得挤出达标块**（Q18）：构造「达标块在重排里被排到 top-k 之外」，断言它仍在最终上下文里。
- **Milvus 超时降级**（S5）：向量臂抛超时，断言仍只用关键词臂作答、且 `biz_degradation_trace` 有 `vector_store/timeout` 一行。

链路相关：

- **FAQ tab 语料按对入库**：上传一份 `问题\t答案` 的 txt，断言 `chunk_count` 等于问答对数（不是 512/64 切出来的块数），且每块 `content` 等于 `问题\n答案`、`heading_path == [问题]`。
- **普通 txt 不受影响**：不带 tab 的 txt 分块行为与改动前一致。
- **`rag_db` seed 幂等**：跑两次 `seed_rag_db`，文档数不变。
- **`knowledge_type` 映射**：同一份 seed 后，`金融政策/*` 落成 `政策`、`公司信息/*` 落成 `FAQ`、`公司个人理财产品手册` 落成 `产品`。
- **内部检索接口的排名与聊天一致**：`/api/internal/knowledge/search` 对同一 query 返回的顺序与聊天检索一致（同一 pipeline）。

### Seam 2 — 纯函数与确定性回放

- **RRF 的纯函数性质**：给定两条已排序列表，融合结果与输入顺序一致；同一块在两路命中时只出现一次、`source == "hybrid"`。
- **分臂判定是纯函数**：给定 `evidence` 与两个阈值，输出「有依据 / 无依据」，覆盖 S1 / S2 / S8 三种组合。
- **回放模式不发起任何外部调用**（S6）：回放下的检索与生成仍走预置数据，`evidence_score` 取预置分，既有 `test_replay_demo_scenarios.py` 的确定性断言全绿。
- **`fake` provider 下重排恒等**（S7）：`rerank_enabled=True` 但 provider 为 fake 时结果顺序与 RRF 序一致，且没有发出 HTTP 请求。

### 要改写的既有断言

- `backend/tests/test_knowledge.py:253`：断言 `meta.chunk_count == 40`（FAQ seed）——markdown 路径不改，这条应保持绿；但同一文件里断言「按 chunk 文本精确检索」的几条要确认在新的 `score` 语义下仍成立。
- `backend/tests/test_customer_service_agent.py:131`（`score=0.45` 假命中必须兜底）：改为构造 `evidence`（向量 0.45 / 关键词 0）而不只是 `ChunkResult.score`，语义不变——**它保护的仍是「0.45 必须兜底」**。
- `backend/tests/test_degradation_paths.py:391`（直接调用 `keyword_search_chunks`）：该函数的返回类型与打分量纲都变了，断言改为 BM25 相关（命中包含关键词的块）。
- 任何构造 `ChunkResult` 并依赖 `source` 二选一逻辑的用例（`retrieval_keyword_score_threshold` 的旧判定）。

## Out of Scope

- cross-encoder / 本地重排模型（Q3 明确不选）。
- 向量库侧的稀疏向量或 BM25 function（Milvus 2.4.15 没有 BM25 function；Q7 选了 Python 侧 BM25）。
- BM25 索引的进程内缓存与持久化（Q15 明确不做）。
- 自定义金融分词词典（Q16 只预留路径）。
- 改写 `faq_seed.md`（已是 `## 问题` 成对，不动）。
- 新增知识类型（Q12）。
- 检索结果的多样性去重 / MMR、按时间衰减、按知识类型加权（不在本次三条建议内）。
- 把重排结果回写入缓存或画像（重排是每次查询的即时增强，不落库）。
- 前端任何改动。

## Further Notes

- **关键词臂从「降级」变成「一等公民」，是这次最需要讲清楚的一次语义升级。** 旧口径下「结果里出现关键词路径」意味着「向量库坏了」；新口径下它只是「这条被字面命中了」。调试留痕里 `source` 的取值分布因此不再等于健康度——判断降级要看 `biz_degradation_trace`，不要再看 `source`。
- **两条阈值必须在同一批合入。** `retrieval_keyword_score_threshold` 的量纲从比例变成 BM25 分，分开合入会出现「新量纲对着旧数字」的静默失准，而它的表现是「该答的兜底了 / 不该答的答了」——都不会有断言失败，除非 04 的回归测试先落地。
- **BM25 分是语料相关的。** df 与 avgdl 随语料变化，同一个问题在不同语料规模下的 BM25 分不同。因此 04 的校准结论要连**语料**一起记录（在脚本输出里打印语料规模），并在语料显著变化时重跑校准。这是选 Q7(c) 相对 Q7(a)（MySQL FULLTEXT 的 TF-IDF）多出来的一份维护成本。
- **tab 嗅探会误伤表格型 txt。** 没有类型门（Q11）就没有办法区分「问答对」与「制表符排版的表格」。若将来真的引入表格型语料，正确的做法是加类型门或改成表格解析，而不是把嗅探启发式堆得更复杂。
- **重排是增强，不是链路的一环。** 任何「重排失败 → 整体检索失败」的实现都是错的；同理，任何「用重排序决定兜底」的实现都违反 Q9。`rerank` 这一条 `DEPENDENCY_RERANK` 的存在意义是让「系统有多少时间在没有重排的情况下工作」可统计。
- **`score` 在重排降级时会变成归一化 RRF。** 它仍是 0~1 且单调不增，但不再跨查询可比——如果将来有界面要展示「这条有多相关」，应当读 `evidence_score`（有明确量纲），而不是归一化分。
