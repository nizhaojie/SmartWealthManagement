# 02 — 客户侧「我的方案」页

**What to build:** 客户应用新增一级导航「我的方案」，页面分「已放行方案」与「方案请求进度」两个分区，点一份方案进入独立详情路由。产品筛选页交出请求列表、只留「请顾问出具方案」按钮，提交成功后跳到本页。

两个分区不合成一条时间线：直接生成的方案没有对应请求（内部端的「为客户发起生成」传 `advisory_request_id=null`），以请求为主键会出现孤儿；而「等待中」与「已出具」是两种不同的状态，混排会让客户分不清哪条在等他、哪条已经好了。

**Blocked by:** 01 — 客户送达视图与客户侧方案接口

**Status:** ready-for-agent

- [ ] `apps/customer/src/advisory/api.ts` 补 `listReleasedPlans()`（`GET /api/customer/advisory/plans`）与 `getReleasedPlan(finalId)`（`GET /api/customer/advisory/plans/{final_id}`）
- [ ] `apps/customer/src/advisory/types.ts` 补客户送达视图的类型（对齐 `serialize_final_for_customer`），并把已有 `AdvisoryRequest` 里的 `customer_id` 去掉
- [ ] 路由：`/advisory`（name `advisory`）+ `/advisory/plans/:finalId`（name `advisory-plan`）
- [ ] `shell/CustomerShell.vue` 的 `navItems` 增加第 5 项「我的方案」（`key` 与 path 同名）
- [ ] 「已放行方案」分区：每份一行摘要（出具时间、出具顾问、产品数），点击进详情
- [ ] 「方案请求进度」分区：`products/AdvisoryRequestList.vue` 迁入 `advisory/`，原位置删除
- [ ] 空状态两级：无定稿但有请求 → 渲染请求进度；两者都无 → 「还没有提交过方案请求」+ 前往产品筛选的按钮
- [ ] 详情页渲染：出具顾问、放行时间、时效提示（「出具于 X（N 天前）」+ 「本方案基于出具时点的画像与市场数据」）、产品清单、配置建议、免责声明
- [ ] 详情页**不渲染**综合得分、排序依据与推荐理由
- [ ] 产品筛选页：移除请求列表，`requestAdvisory()` 成功后 `router.push({ name: "advisory" })`
- [ ] **组件测试：三种首屏状态（有定稿 / 只有请求 / 都无）各渲染正确**
- [ ] **组件测试：详情页不渲染综合得分与推荐理由；渲染出具顾问、放行时间与免责声明**
- [ ] 组件测试：侧栏第 5 项存在且能到 `/advisory`；提交请求后跳到 `/advisory`
- [ ] 更新 `products/ProductScreeningPage.spec.ts` 中与请求列表相关的用例（列表已迁走，改为断言跳转）
