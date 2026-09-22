# 02 — 客户侧流水合并读扩到三张表

**What to build:** 客户在自己那**一张**流水里看到充值。合并读从两表升为三表扇入，否则充值行会整行消失——**不报错**，与 ADR-0019 那次是同一个失败形态。

**Blocked by:** 01 — 充值的载体与受理

**Status:** ready-for-agent

- [x] `backend/app/customer_assets/service.py` 新增 `_deposit_rows()`，`list_transactions()` 从两表合并升为**三表扇入**
- [x] 排序键的来源序号加 `_FLOW_DEPOSIT=2`（既有两个是 `_FLOW_TRANSACTION=0` / `_FLOW_TRANSFER=1`），排序仍是 `(traded_at, 表来源序号, id)` 倒序
- [x] `serialize_deposit()` 与 `serialize_transfer()` 同形；`_serialize_flow` 对充值行给出 `product_code` / `product_name` / `shares` / `nav` / `fee` / `payee_name` / `payee_account` 全为 `None`
- [x] 类型筛选：`transaction_type=充值` 只读 `fin_deposit`（与既有两个分支同形）
- [x] **仍然不分页**（既有口径）
- [x] 把「这是一处 N 表扇入」写成函数注释里的模式，加第四类记录时照着做
- [x] 断言：充值出现在客户侧流水里，且带 `DP` 前缀的流水号
- [x] 断言：流水同时含申购、赎回、转账、充值四类，按时间倒序
- [x] 断言：筛一个三张表都不认的类型返回空，不做无差别兜底（`test_customer_transfer_and_merged_history.py` 的既有断言延续）

**实现落点：** `backend/app/customer_assets/service.py`；断言落进 `backend/tests/test_customer_deposit.py`（与 #01 同一个文件，两者是同一个 HTTP seam）。

### 为什么单独成一份

ADR-0019 记过这件事：这一处改动的失败形态是**静默的**——`INNER JOIN fin_product` 漏了转账、或者合并读漏了一张表，都不会报错，只是那一行在客户眼前消失。给它一个自己的验收，是为了让「流水里有充值」这条断言有一个明确的归属，而不是夹在 #01 的十条断言里被跳过。

### 交接给 #03

接口在这一份里就把充值行给全（包括 `DP` 流水号与两个 `None` 的对手方位），界面的表格结构**不动**：`TransactionHistory.vue:14-23` 已经定了「缺失的一项显示为「—」，不编造、也不留空单元格」。
