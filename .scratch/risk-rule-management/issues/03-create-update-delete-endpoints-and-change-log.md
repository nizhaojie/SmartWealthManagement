# 03 — 创建、修改、删除接口与留痕扩展

**What to build:** `POST` / `PATCH /{id}` / `DELETE /{id}` 三个写接口，全部走 #02 的校验入口、全部要求非空理由、全部各记一条变更；既有的启停与阈值接口保留，启停的理由从可空收紧为必填。

**Blocked by:** `risk-rule-management` #02 — 字段×算子允许矩阵、值域与 schema 端点

**Status:** implemented

- [x] `POST /api/internal/risk-rules`：全参数创建，`rule_code` 系统分配，`description` 留空则按 `{作用域}{字段标签}{measure} {符号} 阈值 {阈值文本}` 自动生成，`enabled` 默认 true
- [x] `POST` 落一条「规则新建」：`old_value` 为 `{}`，`new_value` 为整份配置快照
- [x] `PATCH /api/internal/risk-rules/{id}`：只接受 `rule_name` / `category` / `description` / `alert_level` / `weight` / `reason`
- [x] `PATCH /{id}` **收到 `field` / `operator` / `window_hours` / `threshold` / `enabled` 任一字段就 400**——不接受比静默忽略更能说清界线（ADR-0026）
- [x] `PATCH /{id}` 落一条「规则修改」，`old_value` / `new_value` 是**整份可编辑配置的快照**，不是只有变了的那个字段
- [x] `DELETE /api/internal/risk-rules/{id}`：软删（写 `deleted_at`）并落一条「规则删除」；**不级联删掉 `fin_risk_rule_change` 里的历史行**
- [x] 三个新接口全部门控 `require_employee_role(RISK_OFFICER)`
- [x] `PATCH /{id}/enabled` 的理由收紧为必填（原来是可空，见 spec 头表）
- [x] 五个写动作（新建 / 修改 / 删除 / 阈值 / 启停）理由为空一律 400
- [x] `PATCH /{id}` 只改名称时，变更记录里的 `old_value` / `new_value` 仍带全部可编辑字段
- [x] 断言：删除后 `GET /{id}/changes` 仍可读，历史预警详情不受影响
- [x] 断言：非风控专员调用任一写接口被拒

**一条容易顺手做错的地方：** `PATCH /{id}` 若用「哪些字段非空就更新哪些」的写法，一个只带 `rule_name` 的请求会把留痕写成只含名称——于是「这条规则当时是什么样」在记录里就断了。`old_value` / `new_value` 要取的是**整份配置的前后两份快照**。

**实现时补上的三处（都在 checks 的界线内，只是清单没写）：**

- ①已删除的规则不再接受任何写操作（改名 / 调阈值 / 启停 / 再删一次一律 400）：删除是终态（ADR-0027），而「已删行置灰只读」既要有界面的一半，也要有后端的一半。
- ②规则名称与权重各自有了写入侧校验（去空白后非空、≤ 128 字；权重默认 1.00、区间 [0.50, 5.00]），都在 `validation.py`：权重错了不会有异常，只会让置信度与「归到哪个分类」说不清。
- ③`PATCH /{id}` 只带 `reason`、一个可改字段都没带时返回 400：一条什么都没改的「修改」不该产生一条读不出内容的留痕。

**删除留痕的形状：** `old_value` 装整份配置、`new_value` 为空——删除是「新建」那条记录的镜像（无 → 有 / 有 → 无）。行虽然还在库里（软删），但「它当时是什么样」应当能从这一条记录直接读出来，不必再去翻列表的「显示已删除」。

**留给 #04 的一处不一致（spec 的 Further Notes 已认下）：** 启停理由收紧为必填之后，`RiskRulesTab.vue` 里的开关仍按旧协议直接提交——**在 #04 把开关改成「点一下先弹理由」之前，界面上的启停会收到 400**。这一处刻意不提前做：同一个开关在 #04 里还要连同伴随的组件测试一起改，现在动它只会制造一次冲突。
