# 04 — golden 问答集与两条阈值的校准

**What to build:** 把两条兜底阈值从「注释里的经验值」变成「数据集量出来的值」，并把校准固化成可重跑的脚本 + 可回归的测试。本份还要把校准结果写回 `Settings` 与 `.env.example`。

**Blocked by:** 01（校准语料要包含按对拆分的 FAQ）、02（校准的是分臂判定的两个量）

**Status:** ready-for-agent

- [ ] golden 集放 `backend/tests/fixtures/retrieval_golden.json`：正例（问题 → 期望命中的 `source_file` / 关键片段）+ 一批**无关负例**（问题 → 期望什么都不命中）
- [ ] 正例覆盖三类：字面型（`T+1`、`七日年化`、客服电话数字串）、语义型（问法与原文措辞不同）、FAQ 按对拆分后的问题
- [ ] 新增 `backend/scripts/calibrate_retrieval.py`：跑 golden 集，打印**正例与负例的分臂分数分布**、语料规模（分块数）与建议阈值；真实 embedding 需要 key，BM25 部分离线可跑
- [ ] 把校准产出的 `retrieval_score_threshold` 与 `retrieval_keyword_score_threshold` 写回 `backend/app/settings.py` 与 `backend/.env.example`，并更新 `.env.example:109-117` 的注释
- [ ] 新增回归测试（`backend/tests/test_retrieval_calibration.py`，用 fake embedding 的确定性）：断言**正例的达标率高于负例**、负例不达标——只钉相对关系，不钉绝对值
- [ ] 断言：一条明显无关的问题不触发作答（综合 S2 的口径，走 HTTP 层断言兜底话术）
- [ ] 脚本输出里记录语料规模，并在注释里写明「语料显著变化后要重跑」

**注意：** 默认测试用 fake embedding（无 key），因此 CI 里**不能**断言阈值的绝对数值——它只断言「正例比负例得分高、负例不达标」。绝对数值由校准脚本产出、人工复核后写回默认值，这是「真实 embedding 需要 key」这个约束下唯一诚实的分工。**本份必须与 02 同批合入**：`retrieval_keyword_score_threshold` 的量纲在 02 里从「命中字词占比」变成 BM25 分，旧默认值在新量纲下是无效的。

**实现落点：** 新增 `backend/tests/fixtures/retrieval_golden.json`、
新增 `backend/scripts/calibrate_retrieval.py`（复用 `app.knowledge.service.keyword_search_chunks` 与向量臂，或直接调 `search_chunks` 后读 `evidence_score`）、
改 `backend/app/settings.py` 与 `backend/.env.example`（写回校准值）、
新增 `backend/tests/test_retrieval_calibration.py`。

### 几处要写下来的决定

**校准的目标量是 `evidence_score`，不是 `score`。** `score` 在重排降级时是归一化 RRF、跨查询不可比；`evidence_score` 才是「该不该作答」的输入（余弦 / BM25 各自量纲）。校准脚本读错字段会得出一个看着像结论的错数字。

**关键词阈值的校准是离线可跑的，向量阈值不是。** BM25 与 `jieba` 都是本地计算，因此 04 可以在没有任何 key 的环境里产出 T_kw；只有余弦那一侧需要 DashScope key（Q5 已确认 key 已配置）。两者分工不同，不要因为一侧能跑就默认另一侧也能跑。

**BM25 分是语料相关的。** df 与 avgdl 随语料规模变化，同一问题在不同语料上得分不同。因此脚本输出要带语料规模，且这条结论要写进 spec / ADR 的代价清单——这是选 `rank_bm25`（Q7 c）相对 MySQL FULLTEXT（Q7 a）多出来的一份维护成本。
