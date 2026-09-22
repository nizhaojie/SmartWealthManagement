# 04 — 收口：演示脚本与那批说「不做入金」的旧口径

**What to build:** 「不做入金」（Q20）被推翻之后，把这个结论写过的每一处都交代一遍。**不改写历史**：既有 spec 的结论只加「已被 ADR-0023 取代」，不删不改。

**Blocked by:** 01、02、03（要改的那批话，只有在实现落定后才说得准）

**Status:** ready-for-agent

- [ ] `docs/demo-script.md` 第四幕（`:119-129`）：改成「余额不足被拒 → 充值 → 同一笔转账成功」。`wangc1` 充 `5000.00` 后，那笔 `5000.00` 的转账应当走通，余额变成 `2000.00`
- [ ] 同文件 §二「上台前必须知道的三件事」第 2 条（`:43-44`）：把「余额只来自种子，没有入金，换一位余额充足的客户重来」改成「余额的初始值来自种子，应用里有充值入口——余额不足可以当场演示自救」
- [ ] 同文件第四幕的台词（`:124-125`）与 §八 的断言索引（`:154-160`）各加/改一行
- [ ] `operation-advice-and-customer-trading` 的 Q20 与 Out of Scope 第一条：加「已被 ADR-0023 取代」
- [ ] `onboarding-funding-account-and-target-allocation` 的 Solution、Q5 与 Out of Scope 第一条：同上（该 slice 的「开户建资金账户、余额 0」本身不变，只是不再是终态）
- [ ] 清掉已不成立的话（行号在 01–03 落定后会漂，按内容找）：
  - [ ] `backend/app/customer_onboarding.py:13-15,132-135`
  - [ ] `backend/app/order_acceptance/service.py:242-244`
  - [ ] `backend/tests/test_funding_account.py:35`（「种子是可用余额的唯一来源（不做入金）」）
  - [ ] `backend/tests/test_end_to_end_customer_journey.py:75-78` 与 `:200-206` 的 `_fund_customer_account`
  - [ ] `backend/tests/test_operation_advice_draft.py:72-74`
  - [ ] `backend/tests/test_operation_advice_decision.py:79-80` 与 `:140-146` 的 `_fund_account`
- [ ] 上一条里三个测试助手**保留**（余额仍是演示与用例的起点），但注释改为指向充值这条真实路径——它们绕过的是「装库时没有入金」，不是「应用里没有」
- [ ] `docs/roadmap.md` 的 `customer-deposit` 一行：从「拆为四份」改为已完成状态

**实现落点：** `docs/demo-script.md`、`.scratch/operation-advice-and-customer-trading/spec.md`、`.scratch/onboarding-funding-account-and-target-allocation/spec.md`、`docs/roadmap.md`，以及上面列出的四个源码/测试文件。

### 为什么这一份不能省

「不做入金」是一句话，但它被写在**七个地方**。只把功能做出来、不改这些地方，下一个人会拿旧注释当准：他会在 `test_funding_account.py:35` 读到「种子是可用余额的唯一来源」，然后据此驳回一笔正确的改动。**推翻一条决定，要把它写过的每一处都交出来**——这是 `AGENTS.md` 那条「发现需要推翻某条 ADR 时，新增一条记录原因，不要静默偏离」在句子层面的执行。
