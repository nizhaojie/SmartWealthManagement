# 05 — 端到端与既有断言收口

**What to build:** 把「新建一条规则 → 它在下一次交易上真的命中」这条端到端路径走通并断言下来，同时收口本 slice 改动的既有行为（种子语义、启停理由、列表过滤）在别处留下的断言。

**Blocked by:** `risk-rule-management` #04 — 规则管理界面

**Status:** implemented

- [x] 端到端：登录为风控专员 → 新建「单笔金额 ≥ 1 元」（必然命中）→ **已有交易不产生任何新预警** → 补录一笔交易 → 预警列表出现由该规则触发的预警，命中依据落到字段与值
- [x] 端到端：新建 → 改名 → 调阈值 → 停用 → 删除，`GET /{id}/changes` 按时间顺序给出 5 条记录，每条都有理由与操作人姓名
- [x] 端到端：删除后列表默认看不到，打开「显示已删除」能看到且置灰，其变更记录可打开
- [x] 收口：`seed` 相关断言改为「表为空才播种」的语义，删除「重启后补种缺失规则」这类旧预期
- [x] 收口：启停相关断言补上「理由为空被拒」
- [x] 收口：规则列表断言补上「默认不含已删行」
- [x] 收口：`docs/demo-script.md` 里凡引用 20 条规则编号的段落复核一遍——编号不再会变，但**规则集不再是 20 条固定的**，脚本里的说法要对得上
- [x] 复核：本 slice 没有新增护栏测试，也没有削弱 ADR-0009 的七条中的任何一条（写入侧校验与护栏 7 是两处：前者管规则配置，后者管交易受理）

**为什么没给写入侧校验登记第 8 条护栏：** ADR-0009 的七条守护的是合规红线（适当性、身份域、只读、不排序、未审核不送达、shared 无业务语义、受理校验不可绕过），而写入侧那三档守护的是「别配出跑不起来的规则」，是工程正确性——它该有的位置是断言，不是护栏表里的一行。本次复核逐条对过：`test_risk_rule_*` 三份新文件里没有以护栏命名的用例，`test_transaction_events_api.py`（护栏 7）与其余护栏用例一行未动。

**实现时的三处口径说明：**

- **「端到端」落在后端 HTTP 层**，与 `test_end_to_end_customer_journey.py` 同一个 seam：登录 → 写规则 →（不回算）→ 补录交易 → 预警，全程真实链路（规则落库、规则引擎求值、命中依据固化）。脚本里「已删行置灰只读」在前端那一半由 `RiskRulesTab.spec.ts` 守着，`test_risk_rule_management_end_to_end.py` 断言的是它背后的服务端事实：默认过滤、`include_deleted=true` 可见、行上的 `deleted_at` 非空。
- **清单里的三条「收口」有两条在 #01 / #03 落地时就一起补上了**（启停理由为空被拒 → `test_risk_rules_api.py::test_enabling_change_without_a_reason_is_rejected`；列表默认不含已删行 → `test_risk_rule_soft_delete_and_seed.py::test_a_soft_deleted_rule_leaves_the_default_listing`）。本 issue 因此只补了种子那一条真正还缺的：`test_seeding_a_table_missing_a_rule_does_not_bring_it_back`——它钉的是旧预期「只补缺失的」的**反面**（**硬删**一行后重跑种子，那一行不回来），而「20 条全被软删后不重新播种」由 #01 的 `test_seeding_a_table_full_of_soft_deleted_rules_is_a_no_op` 钉着。
- **文档清算不止 demo-script.md 一处**：`docs/system-architecture.md` 的「20 条反洗钱规则」也按 ADR-0027 的后果改成「初始 20 条」（该 ADR 写明的正是「凡引用 20 条规则的地方都改成初始 20 条」）；demo-script 另补两处——「一、准备」里「重跑 setup 恢复初始演示状态」要说明**规则集不在复位范围内**，第二幕的 `R0xx` 命中清单要说明它以内置规则健在为前提。
