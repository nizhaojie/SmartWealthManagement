# 02 — 字段×算子允许矩阵、值域与 schema 端点

**What to build:** 一份显式的「字段 × 算子」允许矩阵与字段值域声明，一套写入侧的校验入口，以及一个把这三样连同分类清单一起下发给前端的 `GET /api/internal/risk-rules/schema`。

**为什么它单独成一份：** 这是整个 slice 里唯一一处能防止「配出一条下一笔交易就会炸、或者永远不会命中的规则」的地方。它同时被创建接口与前端下拉依赖，先落地才能写那两边。

**Blocked by:** `risk-rule-management` #01 — 软删、分类 CHECK 与种子语义

**Status:** implemented

- [x] 在 `fields.py`（或 `operators.py`，与 `FIELD_REGISTRY` / `OPERATOR_REGISTRY` 放同一处）加一份显式的允许矩阵：`(field, operator)` 的组合声明，**不写成散落的 `if` 分支**——加一条规则是往表里加一行（`FieldSpec.allowed_operators`，矩阵就是 `FIELD_REGISTRY` 本身）
- [x] 取值不是数值的字段（`product_id`）只允许不比较数值的算子（时间窗去重计数）
- [x] 取值语义是「小时」「百分比」「等级差」的字段不允许求和类聚合（`NON_ADDITIVE_OPERATORS`）
- [x] 每个字段加 `value_range` 声明：`hour_of_day` ∈ [0, 23]，`risk_level_gap` ∈ [-4, 4]，`amount_to_assets_ratio` > 0，`reverse_interval_hours` > 0，金额类字段 > 0（`product_id` 无数值值域，显式 `None`）
- [x] 校验入口按三档顺序执行：名录（category / field / operator / alert_level）→ 搭配矩阵 → 阈值值域；阈值形状仍复用既有的 `normalize_threshold`（`app/risk_monitoring/validation.py`）
- [x] 校验失败一律返回 400 且**说清是哪一档、哪个字段**：消息以「名录/搭配/值域/阈值形状/时间窗校验未通过」开头并带上出错的列与值，`INVALID_THRESHOLD_MESSAGE` 已删除
- [x] `GET /api/internal/risk-rules/schema`：分类（7 个）、字段（key / label / description / 允许的算子 / value_range）、算子（key / label / symbol / scope / threshold_keys）；门控 `require_internal`
- [x] 断言：`field = product_id` + `operator = gt` 被拒，且**库里不落行**（校验入口在任何写入之前；`test_the_rejected_combination_never_reaches_the_database`）
- [x] 断言：`field = hour_of_day` + `threshold = 30` 被拒
- [x] 断言：schema 里每个字段列出的允许算子，与校验矩阵**逐项一致**（双向：schema 列出的组合后端全收，未列出的全拒）

**实现时补上的两处（都在 checks 之内，只是清单没写）：** ①既有的 `PATCH /{id}/threshold` 也改走这个入口——它是唯一改阈值的口子，不接上就等于值域校验可以绕过；②`validate_rule_definition` 顺带校验时间窗与算子的一致性（时间窗算子要正整数窗长、其余算子带窗长则置空），`window_hours` 是判定形状的一部分，两个写入口读同一份判定，比 #03 再散落一次更省事。

**实现时核对出的一处前提有误（本条与 spec 的 Problem Statement 都要改口径）：** spec 说 `product_id` 的取值是字符串 `"P001"`，于是 `product_id` + `gt` 会在求值那一刻抛 `TypeError`。实际不是——`TransactionEvent.product_id`、API 模型与库列三处都是 `int | None`（`context.py`、`transaction_events.py`、`models.py`），`to_comparable` 把它转成 `Decimal`，实测 `evaluate_rule` 正常返回命中（`产品标识 5 > 阈值 3`）。因此：

- **禁配的决定不变**（`product_id` 只允许时间窗去重计数），但理由要按真实类型写：它是**没有含义**的组合（拿标识比大小、把标识求和），不是会崩的组合；
- 这一档挡的主要是「无意义的组合」，而不是「下一笔交易就会炸的组合」——会炸的那一类出现在阈值的类型与算子对不上时（`operators._require_number` 挡的就是它），由形状与值域两档守着。spec 里「这是唯一一处能防止配出一条下一笔交易就会炸的规则的地方」这句据此收窄为「防止配出一条永远不会命中、或者口径没人说得清的规则」；
- 断言本身（`product_id` + `gt` 被拒、且库里不落行）不受影响，照写。

**为什么不让前端自己过滤就完事：** 前端禁掉的选项与后端拒掉的组合一旦漂移，表现是「下拉里能选、一提交被拒」——不会有断言失败，只会有人反复试。后端必须是唯一裁判。
