# 02 — 开户即建资金账户

**What to build:** 「一个客户一个资金账户」是 `CONTEXT.md` 的定义，种子里每位客户都有，只有开户这条路漏了。开户与画像、标签在同一个事务里建出资金账户，余额 0——**入金仍然不做**（Q20 不变），新客户能登录、能看资产页，下单回的是「可用余额不足」而不是「资金账户不存在」。

**Blocked by:** 无前置。

**Status:** implemented

- [x] `open_account` 建 `FundingAccount(customer_id=..., available_balance=Decimal("0.00"))`，与客户、画像在同一事务
- [x] 断言：开户的响应里 `id` 对应的资金账户存在、余额为 `0.00`；客户本人能读到它（`GET /api/customer/funding-account` 不再是 404）
- [x] 断言：新开户客户下一单回「可用余额不足」，不是「资金账户不存在」
- [x] 既有测试里「先开户、再 INSERT 资金账户」的助手改为 UPDATE：`test_end_to_end_customer_journey.py`、`test_operation_advice_draft.py`、`test_operation_advice_decision.py`、`test_operation_advice_console.py`、`test_operation_advice_options.py`
- [x] `docs/demo-script.md` 第六幕的台词改为「新开户客户的余额是 0」，不再说「没有资金账户」
