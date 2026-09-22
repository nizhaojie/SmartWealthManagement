# 01 — FAQ 按对拆分，并给 `rag_db/` 补幂等 seed

**What to build:** 一组问答是 FAQ 的最小完整语义单元，现在它被 512/64 的滑动窗口切碎了。本份让 `_parse_txt` 识别连续的 `问题\t答案` 行、**一组问答一个分块**，并给 `rag_db/` 的正式语料补一个幂等 seed 脚本。这一份独立于检索链路（02/03/04），可以最先合入。

**Blocked by:** 无（`parse_document` 与 `ingest_document` 均已就绪）

**Status:** ready-for-agent

- [ ] `_parse_txt`（`backend/app/knowledge/parsers.py:39`）逐行扫描：一行含 tab 且第一个 tab 之前非空 → 问答对（`split("\t", 1)`，答案内再有 tab 不二次切分）
- [ ] 每组问答对产出一个 `Section`：`heading_path = [question]`、`text = question + "\n" + answer`
- [ ] 不含 tab 的行按原样累积成普通 Section（`heading_path = []`）；遇问答行先 flush、文件末尾再 flush；整体保持文件原始顺序
- [ ] **`parse_document` 签名不变**、不接收 `knowledge_type`（Q11 的纯内容嗅探）
- [ ] 问答对仍走既有的 `_chunk_sections`（512/64）——短问答因此是一对一块，超长问答才会被二次切分
- [ ] 新增 `backend/app/knowledge/seed_rag_db.py`：递归扫描仓库根的 `rag_db/`，收 `.md` 与 `.txt`
- [ ] 目录 → 类型映射写在脚本里一处：`金融政策/` → `政策`、`公司业务/个人理财产品手册.md` → `产品`、其余 → `FAQ`
- [ ] `source_file` = 相对 `rag_db/` 的 POSIX 路径（如 `公司信息/企业信息.md`），`title` = 文件名去扩展名
- [ ] seed 幂等：已存在同 `source_file` 且 `status = active` 的文档即跳过（与 `seed_faq.py` 同一口径）
- [ ] 断言：上传一份 `问题\t答案` 的 txt，`chunk_count` 等于问答对数，不是滑动窗口切出来的块数
- [ ] 断言：每块 `content == 问题\n答案`、`heading_path == [问题]`
- [ ] 断言：不带 tab 的 txt 分块行为与改动前一致
- [ ] 断言：`seed_rag_db` 跑两次，文档数不变
- [ ] 断言：seed 后 `金融政策/*` 落 `政策`、`公司信息/*` 落 `FAQ`、`公司业务/个人理财产品手册.md` 落 `产品`

**注意：** 这一份**不改** `backend/app/knowledge/fixtures/faq_seed.md`（它已经是 `## 问题` 成对，`test_knowledge.py:253` 钉着 `chunk_count == 40`，应保持绿）。也不要顺手把 FAQ 拆分的启发式堆得更复杂——表格型 txt 的误伤是接受的代价（见 spec 的 Further Notes），要治它得加类型门，不是加更多规则。

**实现落点：** 改 `backend/app/knowledge/parsers.py`（`_parse_txt`；如需拆分辅助函数就放同文件，保持 `parse_document` 是唯一入口）、
新增 `backend/app/knowledge/seed_rag_db.py`（形状照 `seed_faq.py`：`seed_rag_db(settings=None)` + `__main__`，复用 `ingest_document` 与 `STATUS_ACTIVE`）、
测试 `backend/tests/test_knowledge.py`（parser 三条）与新增 `backend/tests/test_seed_rag_db.py`（幂等与类型映射两条）。
