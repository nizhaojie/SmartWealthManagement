# 01 — 目标配置的合计必须为 100

**What to build:** 目标配置是**比例**。开户时填进去的各类资产占比一旦合计不是 100，它就不成立——合计 180% 是矛盾，合计 60% 会被下游的「100 减去其余」把差额记到被侧重的类别上。校验收在一处函数里，两个写入路径（开户采集、理财顾问手工修正标签）都过它；开户表单显示实时合计并在提交前拦一道。

**Blocked by:** 无前置。

**Status:** implemented

- [x] 新增 `backend/app/customer_profile/target_allocation.py`：`validate_target_allocation(value)`，合计必须为 100、每项必须是不为负的数字，否则 `AppError(400, ...)`
- [x] `open_account` 与 `write_tag`（`tag_key == "target_allocation"`）都调用它——手工修正标签那条路径不能绕过去
- [x] 错误文案给出实际合计
- [x] `apps/internal/src/customer-relations/onboarding.ts`：合计与错误文案做成纯函数；`OpenAccountForm.vue` 显示实时合计、提交前拦截
- [x] 新增 `backend/tests/test_customer_onboarding.py` 覆盖：合计 100 通过、合计 >100 被拒绝且客户没有落库、合计 <100 被拒绝、手工修正标签同样被拦
- [x] 新增 `apps/internal/src/customer-relations/onboarding.spec.ts` 覆盖纯函数
- [x] review 修正：合计比到百分位（表单显示的是这个刻度）、「五项全为 0」与空字典同义、错误显示在目标配置那一块下面
