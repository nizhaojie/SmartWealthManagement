# 02 — 字段×算子允许矩阵、值域与 schema 端点

**What to build:** 一份显式的「字段 × 算子」允许矩阵与字段值域声明，一套写入侧的校验入口，以及一个把这三样连同分类清单一起下发给前端的 `GET /api/internal/risk-rules/schema`。

**为什么它单独成一份：** 这是整个 slice 里唯一一处能防止「配出一条下一笔交易就会炸、或者永远不会命中的规则」的地方。它同时被创建接口与前端下拉依赖，先落地才能写那两边。

**Blocked by:** `risk-rule-management` #01 — 软删、分类 CHECK 与种子语义

**Status:** ready-for-agent

- [ ] 在 `fields.py`（或 `operators.py`，与 `FIELD_REGISTRY` / `OPERATOR_REGISTRY` 放同一处）加一份显式的允许矩阵：`(field, operator)` 的组合声明，**不写成散落的 `if` 分支**——加一条规则是往表里加一行
- [ ] 取值不是数值的字段（`product_id`）只允许不比较数值的算子（时间窗去重计数）
- [ ] 取值语义是「小时」「百分比」「等级差」的字段不允许求和类聚合
- [ ] 每个字段加 `value_range` 声明：`hour_of_day` ∈ [0, 23]，`risk_level_gap` ∈ [-4, 4]，`amount_to_assets_ratio` > 0，`reverse_interval_hours` > 0，金额类字段 > 0
- [ ] 校验入口按三档顺序执行：名录（category / field / operator / alert_level）→ 搭配矩阵 → 阈值值域；阈值形状仍复用既有的 `normalize_threshold`
- [ ] 校验失败一律返回 400 且**说清是哪一档、哪个字段**，不复用 `INVALID_THRESHOLD_MESSAGE` 那样一句笼统的话
- [ ] `GET /api/internal/risk-rules/schema`：分类（7 个）、字段（key / label / description / 允许的算子 / value_range）、算子（key / label / symbol / scope / threshold_keys）；门控 `require_internal`
- [ ] 断言：`field = product_id` + `operator = gt` 被拒，且**库里不落行**
- [ ] 断言：`field = hour_of_day` + `threshold = 30` 被拒
- [ ] 断言：schema 里每个字段列出的允许算子，与校验矩阵**逐项一致**（同一份来源，不是两份清单互抄）

**为什么不让前端自己过滤就完事：** 前端禁掉的选项与后端拒掉的组合一旦漂移，表现是「下拉里能选、一提交被拒」——不会有断言失败，只会有人反复试。后端必须是唯一裁判。
