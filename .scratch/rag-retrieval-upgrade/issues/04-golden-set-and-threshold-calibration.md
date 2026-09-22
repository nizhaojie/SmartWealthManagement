# 04 — golden 问答集与两条阈值的校准

**What to build:** 把两条兜底阈值从「注释里的经验值」变成「数据集量出来的值」，并把校准固化成可重跑的脚本 + 可回归的测试。本份还要把校准结果写回 `Settings` 与 `.env.example`。

**Blocked by:** 01（校准语料要包含按对拆分的 FAQ）、02（校准的是分臂判定的两个量）

**Status:** implemented

- [x] golden 集放 `backend/tests/fixtures/retrieval_golden.json`：正例（问题 → 期望命中的 `source_file` / 关键片段）+ 一批**无关负例**（问题 → 期望什么都不命中）
- [x] 正例覆盖三类：字面型（`T+1`、`七日年化`、客服电话数字串）、语义型（问法与原文措辞不同）、FAQ 按对拆分后的问题
- [x] 新增 `backend/scripts/calibrate_retrieval.py`：跑 golden 集，打印**正例与负例的分臂分数分布**、语料规模（分块数）与建议阈值；真实 embedding 需要 key，BM25 部分离线可跑
- [x] 把校准产出的 `retrieval_score_threshold` 与 `retrieval_keyword_score_threshold` 写回 `backend/app/settings.py` 与 `backend/.env.example`，并更新 `.env.example:109-117` 的注释
- [x] 新增回归测试（`backend/tests/test_retrieval_calibration.py`，用 fake embedding 的确定性）：断言**正例的达标率高于负例**、负例不达标——只钉相对关系，不钉绝对值
- [x] 断言：一条明显无关的问题不触发作答（综合 S2 的口径，走 HTTP 层断言兜底话术）
- [x] 脚本输出里记录语料规模，并在注释里写明「语料显著变化后要重跑」

**注意：** 默认测试用 fake embedding（无 key），因此 CI 里**不能**断言阈值的绝对数值——它只断言「正例比负例得分高、负例不达标」。绝对数值由校准脚本产出、人工复核后写回默认值，这是「真实 embedding 需要 key」这个约束下唯一诚实的分工。**本份必须与 02 同批合入**：`retrieval_keyword_score_threshold` 的量纲在 02 里从「命中字词占比」变成 BM25 分，旧默认值在新量纲下是无效的。

**实现落点：** 新增 `backend/tests/fixtures/retrieval_golden.json`、
新增 `backend/scripts/calibrate_retrieval.py`（复用 `app.knowledge.service.keyword_search_chunks` 与向量臂，或直接调 `search_chunks` 后读 `evidence_score`）、
改 `backend/app/settings.py` 与 `backend/.env.example`（写回校准值）、
新增 `backend/tests/test_retrieval_calibration.py`。

### 几处要写下来的决定

**校准的目标量是 `evidence_score`，不是 `score`。** `score` 在重排降级时是归一化 RRF、跨查询不可比；`evidence_score` 才是「该不该作答」的输入（余弦 / BM25 各自量纲）。校准脚本读错字段会得出一个看着像结论的错数字。

**关键词阈值的校准是离线可跑的，向量阈值不是。** BM25 与 `jieba` 都是本地计算，因此 04 可以在没有任何 key 的环境里产出 T_kw；只有余弦那一侧需要 DashScope key（Q5 已确认 key 已配置）。两者分工不同，不要因为一侧能跑就默认另一侧也能跑。

**BM25 分是语料相关的。** df 与 avgdl 随语料规模变化，同一问题在不同语料上得分不同。因此脚本输出要带语料规模，且这条结论要写进 spec / ADR 的代价清单——这是选 `rank_bm25`（Q7 c）相对 MySQL FULLTEXT（Q7 a）多出来的一份维护成本。

## 落地要点

- **校准结果（2026-09，语料 = 10 文档 / 348 分块，`text-embedding-v3`）**：向量臂负例最高 0.4626、语义正例最低 0.6791 → `RETRIEVAL_SCORE_THRESHOLD=0.57`；关键词臂负例最高 10.6322、字面 / FAQ 正例最低 15.5196 → `RETRIEVAL_KEYWORD_SCORE_THRESHOLD=13`。11 条正例全部进了候选池，建议值都取「最差负例与最低正例的中点」。
- **向量臂本次降级时，脚本拒绝给向量建议。** `RetrievedChunks.evidence` 分不清「向量臂没块达标」与「向量臂整个降级」——降级时 `evidence["vector"]` 恒为 0，算出来的建议值是「向量库坏了」而不是「余弦分布如何」。脚本因此跑之前记下 `biz_degradation_trace` 的最大 id，跑完查这一段里有没有 `vector_store` 依赖的记录，有就在报告里标 `[WARN]` 并说明不可写回（fake embedding 同理）。「向量臂没命中」与「向量臂没跑起来」混在一起是这套分臂设计最容易出错的地方，工具层先把它分开。
- **golden 的 `kind` 决定它服务哪条臂**：`literal` / `faq` 归关键词臂（逐字命中），`semantic` 归向量臂。脚本按这个映射分别提两条臂的建议值——把语义型正例混进关键词臂的正例集会让「最低正例」掉到 0。
- **`.env` 也要一起改。** `Settings` 的 `env_file` 指着 `backend/.env`，只改 `.env.example` 与 `settings.py` 的话，本机跑起来的仍是旧阈值（`retrieval_keyword_score_threshold` 停在 0.35，无关问题照答）。`.env` 不进版本库，但它才是运行时真读的那份。
- **回归测试不读 `backend/.env`**（`Settings(_env_file=None)`）：它钉的是 `settings.py` 里的代码默认值。读 `.env` 会让这条回归时而检查代码、时而检查某个人机器上的历史遗留值。
- **fake embedding 下向量臂不可分离，这是实测而非推测**：语义型正例最低余弦 0.0741、负例最高 0.2114（字面哈希本质是字面匹配，语义型正例在它眼里没有优势）。因此 CI 里只对**关键词臂**断言「建议阈值能把正负例分开」；向量臂只进「负例不达标」那一半（走生产的 `has_retrieval_evidence`），另加一条「正例整体高于负例」的相对关系。绝对数值只能由真实 embedding 产出。
- **04 落地顺手修了 `test_degradation_paths.py` 的两处**，都是「02 把关键词臂提成一等公民」的连带效应：一是该文件的 `_test_settings` 没注入关键词阈值，校准后的默认值（13）会把降级路径的「成功」判成兜底——目标分块在测试库的 FAQ 语料里只拿到约 11.5 分（同主题的 `faq_seed` 分块稀释了 df），因此显式注入 10.0；二是 `test_vector_search_timeout_falls_back_to_keyword_retrieval` 用固定 `sleep(0.4)` 制造超时，而超时预算要从关键词臂的耗时里扣、`jieba` 冷启动一次约 0.9s（隔离运行本文件时就是这种情形），于是 future 先跑完、超时不再发生——改成让替身阻塞到用例放行。
- **dev 语料重建过一次**：`knowledge_chunks` 里存在同一 `knowledge_id` 下混着另一份文档的陈旧向量（命中内容的 `source_file` 与正文对不上），是历史 seed 反复写入留下的。语料是 MySQL 源文档的派生物，因此直接删集合、按 `seed_faq` + `seed_rag_db` 重灌（348 分块，无重复）。校准之前必须先确认语料干净，否则量的是污染后的分布。
