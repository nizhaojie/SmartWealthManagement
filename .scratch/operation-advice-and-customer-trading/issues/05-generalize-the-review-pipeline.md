# 05 — 审核流水线泛化出内容类型

**What to build:** 「投顾内容 / AI 原稿 / 顾问定稿 / 审核」在词汇表里本来就是与类型无关的抽象，只有表是方案专用的。这一份把表补上：审核记录加内容类型与内容引用、回填既有行为「方案」，操作建议复用同一条队列与同一套中断。**不做平行流水线**（ADR-0020）——护栏「未经审核不可送达」必须只有一个出口。

**Blocked by:** 04 — 交易成为风控的真正输入

**Status:** implemented

- [x] 审核记录加内容类型 + 内容引用；**就地加列 + 回填既有行为「方案」**，不改表名、不改 API 路径、不改前端（ADR-0020）
- [x] 方案特有的载荷（候选池快照、配置建议等）留在原表；操作建议的载荷**另建表**，不让方案特有字段以空列形式跟着建议走
- [x] 审核队列与中断恢复按类型无关地工作：队列返回两类内容，各带类型标注
- [x] 同一条内容在审核期间仍然加锁，两类内容共用同一套并发保护
- [x] 断言：既有方案链路的全部用例不改语义地通过（这一步是本次改动的安全网）
- [x] 断言：审核队列同时返回两类内容且各带类型标注

**实现落点：** `backend/migrations/versions/0026_generalize_review_content.py`（加列 + 回填 + 新表）、
`backend/app/db/models.py`（`AdvisoryReview` 的 `content_type` / `content_ref` 与可空的 `draft_id`、
新增 `OperationAdviceDraft`）、`backend/app/advisory/pipeline.py`（内容类型常量与恢复运行时登记）、
`backend/app/advisory/review.py`（`get_review_by_content` / `claim_review` / `resume_review`）、
`backend/app/advisory/queue.py`（合并的待审队列与审核历史）、
`backend/app/advisory/graph.py`（落审核记录时标明类型、登记方案的恢复运行时）；
测试 `backend/tests/test_advisory_pipeline_content_types.py`（新增）。

### 四处写下来的决定

**恢复运行时按内容类型登记，不按类型 if/elif。** 审核记录上的 `thread_id` 指向某一次生成运行，
续跑要用**同一张图**拓扑才接得回中断点，所以 `app.advisory.pipeline` 里是一张登记表，各内容类型的图
在自己的定义处调 `register_resume_graph`（方案在 `graph.py` 底部）。类型没有登记运行时时报错并解锁，
**不回退到别的内容类型的图上**——跑错图就是把一份决定喂给了另一份内容，而不会有任何测试当场发现。

**`content_ref` 与 `draft_id` 并存。** 就地加列意味着不迁移既有外键：方案的 `content_ref` 就是
`draft_id`（回填时写同一个值），操作建议的 `content_ref` 指向新表而 `draft_id` 为空——它是方案特有的列。
回填用的 `server_default='方案'` 在回填之后撤掉，否则以后新增的插入会悄悄变成「方案」。

**队列与历史按类型各查一次再合并，不硬 JOIN。** 两类载荷分表，硬 JOIN 到其中一张会让另一类内容整批
消失（与 `INNER JOIN fin_product` 那个漏点同一类：不报错，只是东西没了）。历史的合并是必要的：
`AdvisoryReviewAudit` 对两类内容是同一张表，按 `draft_id` 内连接会让操作建议的审核留痕整批读不到。
产品名走 `fin_product` 的外连接——产品缺了只该少一个名字，不该让这条建议整行消失。

**操作建议载荷表只有「一个产品、一个方向、一个金额、一条理由」。** 候选池快照、配置建议、画像警示
一个都不带（它们是配置方案特有的，ADR-0020 的 Consequences）；`direction IN ('申购','赎回')` 与
`amount > 0` 落在表上，理由非空。业务操作 Agent 的生成入口是 #06 的活，本份只把载荷与流水线这一侧
打通——测试直接落一条载荷与审核记录来钉住流水线本身。

### 与 #06 的交接

`OperationAdviceDraft` 的写入方（record/get/序列化）与它的 LangGraph 运行时都属于 #06：它要在
`app.advisory.pipeline` 里登记 `CONTENT_TYPE_OPERATION_ADVICE` 的恢复运行时，此后
`claim_review` / `resume_review` 直接可用，不需要再写第二套加锁与恢复。
