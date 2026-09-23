# 02 — 客服图接入数据查询分支

**What to build:** 客服图的 `classify` 增加数据查询一类，确定性路由到复用的 analytics 链路（选视图 → 生成 → 校验 → 执行 → 解读），身份注入改客户口径，结果以文本解读经既有 SSE 送达。三套响应话术齐备：失败/超时（降级留痕）、白名单外、零行。**本份做完即有可演示的完整状态。**

**Blocked by:** `01-customer-domain-semantic-views`

**Status:** ready-for-agent

- [ ] `backend/app/agent/graph.py` 的 `classify` 增加数据查询一类，确定性路由到复用的 analytics 链路节点；不引入 tool-calling
- [ ] 客户侧候选视图目录限白名单：四张 `va_my_*` + `va_product_element`；员工侧其余视图（含预警统计）不在客户候选集
- [ ] 执行前 `SET` 客户凭证标识（来自 `require_customer` 解出的身份）；记忆沿用客服既有短期记忆（JWT `sid`、客户命名空间），上一轮提问并进视图匹配语境
- [ ] 解读输出面向客户的事实性文本，数字直接写进文本，不带投资评价；SSE 帧、`ChatRequest`、前端零改动
- [ ] 失败/超时 → 「暂时查不了，稍后再试或去资产页查看」+ 写降级留痕（复用 `biz_degradation_trace`）；**不回退到知识检索**
- [ ] 白名单外 → 明确告知不在可查范围并列出可查什么；零行 → 如实说没有数据（与失败话术区分）
- [ ] 产品筛选路径：允许风险承受等级作为过滤条件（Cn 筛 R1–Rn），只筛不排序、按产品代码排序，无推荐话术
- [ ] 高风险意图识别路径不变：数据查询的问题照常过它
- [ ] 断言：客户问「我持有哪些产品」得到含自己持仓数字的文本回答
- [ ] 断言：问「我的画像标签是什么」得到白名单外语术，不是知识库兜底答案

**实现落点：** `backend/app/agent/graph.py`、`backend/app/agent/config.py`、`backend/app/analytics/service.py`（身份与目录参数化）、`backend/app/agent/registry.py`；测试沿 `backend/tests/test_analytics_query.py` 与客服链路测试手法。

**验收：** 登录客户 → 问「我持有哪些产品」→ 得到带引用契约之外的文本数据回答（数据回答的依据是查询本身）；「这个月转了多少」可追问（同会话上下文接得上）。
