# 01 — 客户域语义视图与受限账号授权

**What to build:** 为客户侧数据查询新建客户域语义视图（持仓明细、交易流水、资金账户、风险承受等级结论），行级条件锁死为凭证客户、未设置返回零行；受限账号同账号授权新视图与产品要素视图。员工侧五个 `va_*` 视图一行不动。

**Blocked by:** 无

**Status:** ready-for-agent

- [ ] 迁移脚本新建四张客户域视图（命名建议 `va_my_*`）：持仓明细、交易流水（含充值/转账）、资金账户、风险承受等级结论（只含等级结论列）
- [ ] 列面以客户既有 REST 数据面为准：`backend/app/api/customer_assets.py`、`customer_transactions.py`、`funding_account.py`；**本人数据不脱敏**
- [ ] 行级条件沿用迁移 0008 手法：会话变量读身份，**未设置返回零行（fail closed）**；客户侧函数/变量与员工侧命名区分
- [ ] `wealth_analytics` 增授四张新视图 + `va_product_element` 的 SELECT（产品要素本无行级过滤，产品筛选直接用它）
- [ ] 视图各带口径说明与关键词，进视图目录（`backend/app/analytics/catalog.py`），客户侧候选集与员工侧互不可见
- [ ] 断言：不设置身份直接查新视图返回零行
- [ ] 断言：设置客户 A 的身份查新视图，只见客户 A 的行（含注入他人 id 也改不了范围）

**实现落点：** `backend/migrations/versions/`（新迁移，参考 `0008_semantic_views.py`）、`backend/app/analytics/catalog.py`、`backend/app/db/analytics_account.py`；测试沿 `backend/tests/test_semantic_views.py` 手法。

**验收：** 迁移后员工侧五视图行为与现有断言零变化；新视图在未设置身份时返回零行，设置身份后只出凭证客户自己的行。
