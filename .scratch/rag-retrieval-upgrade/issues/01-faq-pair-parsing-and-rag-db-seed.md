# 01 — FAQ 按对拆分，并给 `rag_db/` 补幂等 seed

**What to build:** 一组问答是 FAQ 的最小完整语义单元，现在它被 512/64 的滑动窗口切碎了。本份让 `_parse_txt` 识别连续的 `问题\t答案` 行、**一组问答一个分块**，并给 `rag_db/` 的正式语料补一个幂等 seed 脚本。这一份独立于检索链路（02/03/04），可以最先合入。

**Blocked by:** 无（`parse_document` 与 `ingest_document` 均已就绪）

**Status:** implemented

- [x] `_parse_txt`（`backend/app/knowledge/parsers.py:39`）逐行扫描：一行含 tab 且第一个 tab 之前非空 → 问答对（`split("\t", 1)`，答案内再有 tab 不二次切分）
- [x] 每组问答对产出一个 `Section`：`heading_path = [question]`、`text = question + "\n" + answer`
- [x] 不含 tab 的行按原样累积成普通 Section（`heading_path = []`）；遇问答行先 flush、文件末尾再 flush；整体保持文件原始顺序
- [x] **`parse_document` 签名不变**、不接收 `knowledge_type`（Q11 的纯内容嗅探）
- [x] 问答对仍走既有的 `_chunk_sections`（512/64）——短问答因此是一对一块，超长问答才会被二次切分
- [x] 新增 `backend/app/knowledge/seed_rag_db.py`：递归扫描仓库根的 `rag_db/`，收 `.md` 与 `.txt`
- [x] 目录 → 类型映射写在脚本里一处：`金融政策/` → `政策`、`公司业务/个人理财产品手册.md` → `产品`、其余 → `FAQ`
- [x] `source_file` = 相对 `rag_db/` 的 POSIX 路径（如 `公司信息/企业信息.md`），`title` = 文件名去扩展名
- [x] seed 幂等：已存在同 `source_file` 且 `status = active` 的文档即跳过（与 `seed_faq.py` 同一口径）
- [x] 断言：上传一份 `问题\t答案` 的 txt，`chunk_count` 等于问答对数，不是滑动窗口切出来的块数
- [x] 断言：每块 `content == 问题\n答案`、`heading_path == [问题]`
- [x] 断言：不带 tab 的 txt 分块行为与改动前一致
- [x] 断言：`seed_rag_db` 跑两次，文档数不变
- [x] 断言：seed 后 `金融政策/*` 落 `政策`、`公司信息/*` 落 `FAQ`、`公司业务/个人理财产品手册.md` 落 `产品`

**注意：** 这一份**不改** `backend/app/knowledge/fixtures/faq_seed.md`（它已经是 `## 问题` 成对，`test_knowledge.py:253` 钉着 `chunk_count == 40`，应保持绿）。也不要顺手把 FAQ 拆分的启发式堆得更复杂——表格型 txt 的误伤是接受的代价（见 spec 的 Further Notes），要治它得加类型门，不是加更多规则。

**实现落点：** 改 `backend/app/knowledge/parsers.py`（`_parse_txt`；如需拆分辅助函数就放同文件，保持 `parse_document` 是唯一入口）、
新增 `backend/app/knowledge/seed_rag_db.py`（形状照 `seed_faq.py`：`seed_rag_db(settings=None)` + `__main__`，复用 `ingest_document` 与 `STATUS_ACTIVE`）、
测试 `backend/tests/test_knowledge.py`（parser 三条）与新增 `backend/tests/test_seed_rag_db.py`（幂等与类型映射两条）。

## 落地要点

- **问答两侧的空白是归一化掉的**：`question` / `answer` 各自 `strip()` 后再拼 `question + "\n" + answer`。这不只是好看——仓库在 Windows 上按 CRLF 检出时，`\r` 会是行长的一部分，不 strip 就会进 `heading_path`。
- **「第一个 tab 之前非空」用 `question.strip()` 的真值判**：所以 `"  \t答案"` 这种空白前缀行按普通文本入缓冲，而不是产出一个 `heading_path = ["  "]` 的问答块。
- **seed 只收 `.md` / `.txt`**，没有复用 `parsers.is_supported`（那个还收 `.docx`）；语料目录的白名单是 seed 自己的口径，集中写在 `SUPPORTED_SUFFIXES`。
- **`seed_rag_db` 的测试跑完会把这一批语料下架**：这九份真实语料留在共用的测试库里会改变其他用例的检索排序（关键词兜底路径按命中字面量打分，语料一多就出现并列，`test_degradation_paths` 里 `citations[0]` 的断言就是这么被打歪的）。要验证的是 seed 的行为，不是「库里常备一份语料」。
- **`rag_db/` 目前仍是未纳入 git 的工作区文件**，seed 与它的测试都依赖它。要不要收进仓库由语料所有者定，本份没有擅自 `git add`。
