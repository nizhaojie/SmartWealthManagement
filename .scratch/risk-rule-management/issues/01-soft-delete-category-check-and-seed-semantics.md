# 01 — 软删、分类 CHECK 与种子语义

**What to build:** 规则表能区分「还在用」与「已删除」，分类列被约束到与代码常量一致的清单，变更留痕的类型扩为 5 个；种子从「只补缺失」改为「表为空才播种」，规则一旦入库就完全归风控专员，不再有任何补种职责。

**为什么先做这一层：** 后面的创建/修改/删除都建立在「一行可以是已删除的」这个前提上；而种子语义不改，专员删掉的规则会在下次启动时复活——删除这个动作就还没有意义。

**Blocked by:** `risk-monitoring-agent` #05 — 风控专员自然语言查询

**Status:** implemented

- [x] 迁移 0032：`fin_risk_rule` 加 `deleted_at DATETIME NULL` 与索引
- [x] 迁移 0032：`fin_risk_rule` 补 `ck_risk_rule_category`，清单与 `rules.py:47-53` 的 7 个分类常量逐字一致（沿用 `0015` 的体例：库里的约束与代码里的注册表是同一份清单）
- [x] 迁移 0032：`fin_risk_rule_change` 的 `ck_risk_rule_change_type` 扩为 5 个值——规则新建 / 规则修改 / 规则删除 / 阈值调整 / 启停变更
- [x] `enabled_rule_specs` 过滤 `deleted_at is null`：**软删的规则不再参与匹配**，已有预警不受影响
- [x] `list_rules` 默认过滤软删行，并接受 `include_deleted` 开关（服务端过滤，不要留给前端）
- [x] `rule_code` 分配函数：取**曾经出现过的最大值 + 1**，格式 `R%03d`；**不过滤软删行**——已删编号照样占位，历史预警快照里的 `R0xx` 永远指向同一条规则
- [x] `_seed_risk_rules` 改为「表为空才播种」；判断用 `count(*)` 而**不是** `count(*) where deleted_at is null`
- [x] 写一个断言：把 20 条全部软删后重启，不重新播种也不撞 `uk_risk_rule_code`
- [x] 写一个断言：删除 R020 后分配到的下一条编号不是 R020

**这条判断写错会怎样：** 若按 `deleted_at is null` 数行数，20 条全被软删后表会被判为「空」，种子重新插入 R001–R020 撞上唯一约束，**服务起不来**。
