# 03 — 「交易」页的第四个入口与流水呈现

**What to build:** 客户在「交易」页看到一个「充值」入口，提交后余额当场变大；在资产页的流水里，充值行显示为「产品 —、收款人 —、类型 充值」。

**Blocked by:** 01（接口）、02（流水读模型）

**Status:** ready-for-agent

- [ ] `apps/customer/src/trading/api.ts` 加 `deposit()`；`apps/customer/src/trading/types.ts` 加 `DepositRequest`
- [ ] `TradingPage.vue` 加**第四个同构卡片**：`data-testid="deposit-form"`、字段「金额（元）」`name="deposit-amount"`、按钮 `name="submit-deposit"`，**追加在既有三张之后**——「买 → 卖 → 出」的顺序不动
- [ ] 提交成功后刷新可用余额并给出成功提示（沿用 `submitPurchase` 的形状，不要新造一套）
- [ ] 失败文案走既有 `apps/customer/src/trading/failure.ts`：金额必须大于零、资金账户不存在各一条
- [ ] `apps/customer/src/assets/TransactionHistory.vue`：`TRANSACTION_TYPES`（`:12`）加「充值」，并改掉 `:11` 那句「转账是唯一的没有产品、有收款人的那一类」
- [ ] `apps/customer/src/funding/types.ts:4` 的注释「也不做入金（余额来自种子）」删掉
- [ ] 流水**表格结构不动**：充值行的产品列与收款人列按既有规矩显示「—」（`productLabel` / `payeeLabel` 已经是这个行为）
- [ ] vitest：纯函数与失败文案；不挂组件
- [ ] **不在资产页新增入口**：资产页是「看」的页面，交易页是「动」的页面（Q10）

**实现落点：** `apps/customer/src/trading/`（`api.ts`、`types.ts`、`TradingPage.vue`、`failure.ts`）、`apps/customer/src/assets/TransactionHistory.vue`、`apps/customer/src/funding/types.ts`。

### 一处刻意的克制

充值只有一个输入框，因此卡片会比既有的三张矮。不要为了「整齐」给它加示例金额、快捷金额或说明段落——这一份只做入口，四张卡片的同构比四张卡片的高度一致更重要。
