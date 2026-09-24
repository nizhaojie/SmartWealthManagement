# 03 — 创建、修改、删除接口与留痕扩展

**What to build:** `POST` / `PATCH /{id}` / `DELETE /{id}` 三个写接口，全部走 #02 的校验入口、全部要求非空理由、全部各记一条变更；既有的启停与阈值接口保留，启停的理由从可空收紧为必填。

**Blocked by:** `risk-rule-management` #02 — 字段×算子允许矩阵、值域与 schema 端点

**Status:** ready-for-agent

- [ ] `POST /api/internal/risk-rules`：全参数创建，`rule_code` 系统分配，`description` 留空则按 `{作用域}{字段标签}{measure} {符号} 阈值 {阈值文本}` 自动生成，`enabled` 默认 true
- [ ] `POST` 落一条「规则新建」：`old_value` 为 `{}`，`new_value` 为整份配置快照
- [ ] `PATCH /api/internal/risk-rules/{id}`：只接受 `rule_name` / `category` / `description` / `alert_level` / `weight` / `reason`
- [ ] `PATCH /{id}` **收到 `field` / `operator` / `window_hours` / `threshold` / `enabled` 任一字段就 400**——不接受比静默忽略更能说清界线（ADR-0026）
- [ ] `PATCH /{id}` 落一条「规则修改」，`old_value` / `new_value` 是**整份可编辑配置的快照**，不是只有变了的那个字段
- [ ] `DELETE /api/internal/risk-rules/{id}`：软删（写 `deleted_at`）并落一条「规则删除」；**不级联删掉 `fin_risk_rule_change` 里的历史行**
- [ ] 三个新接口全部门控 `require_employee_role(RISK_OFFICER)`
- [ ] `PATCH /{id}/enabled` 的理由收紧为必填（原来是可空，见 spec 头表）
- [ ] 五个写动作（新建 / 修改 / 删除 / 阈值 / 启停）理由为空一律 400
- [ ] `PATCH /{id}` 只改名称时，变更记录里的 `old_value` / `new_value` 仍带全部可编辑字段
- [ ] 断言：删除后 `GET /{id}/changes` 仍可读，历史预警详情不受影响
- [ ] 断言：非风控专员调用任一写接口被拒

**一条容易顺手做错的地方：** `PATCH /{id}` 若用「哪些字段非空就更新哪些」的写法，一个只带 `rule_name` 的请求会把留痕写成只含名称——于是「这条规则当时是什么样」在记录里就断了。`old_value` / `new_value` 要取的是**整份配置的前后两份快照**。
