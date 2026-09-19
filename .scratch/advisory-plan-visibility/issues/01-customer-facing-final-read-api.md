# 01 — 客户送达视图与客户侧方案接口

**What to build:** 顾问定稿在客户侧的呈现与出口。客户能读到的是**客户送达视图**——定稿里属于客户可见视图的那部分，裁剪在服务端一个函数里完成，内部的 `warnings`、评分、排序依据、推荐理由与内部标识一概不出现在响应体上。

这里最容易做成「前端不显示就好了」：字段照样发出去，页面不上屏。那样客户可见视图的边界就退化成前端的展示习惯，下一个人接一个导出口（导出、分享、第三方）时它就不成立了。

**Blocked by:** 无（`get_latest_final_for_customer` / `serialize_final` 与 `/api/customer/advisory/plan` 均已就绪，本 issue 是裁剪与新增出口）

**Status:** ready-for-agent

- [ ] 在 `app/advisory/final.py` 新增 `serialize_final_for_customer`；`serialize_final` **保持不动**，继续供内部端使用
- [ ] 客户送达视图保留：`id`、`released_at`、`advisor_name`、`disclaimer`、`allocation_suggestion`，以及每款产品的 `product_code` / `product_name` / `product_type` / `risk_level` / `expected_return` / `term_days`
- [ ] 客户送达视图不含：`warnings`、`composite_score`、`score_breakdown`、`reason`、`content_classification`、`customer_id`、`advisor_id`、`draft_id`
- [ ] 新增 `GET /api/customer/advisory/plans`：该客户的定稿列表（按 `released_at` 倒序）；无已放行方案时返回**空数组**，不是 404
- [ ] 新增 `GET /api/customer/advisory/plans/{final_id}`：**不属于调用者的 id 返回 404**（不是 403）
- [ ] 现有 `GET /api/customer/advisory/plan` 改为返回客户送达视图，404 语义（尚无已放行的方案）不变
- [ ] 三个出口共用同一个序列化函数，不与 `serialize_final` 合流
- [ ] `app/advisory_request/service.py` 的 `_serialize` 去掉 `customer_id`
- [ ] **护栏测试：客户 A 用自己的令牌按 id 读客户 B 的定稿 → 404**
- [ ] **护栏测试：客户侧方案响应里不出现上述内部字段；`advisory-requests` 响应里不出现 `customer_id`**
- [ ] 改写既有断言，语义不变、改比裁剪后的形状：`tests/test_advisory_review.py:250-285`、`tests/test_end_to_end_customer_journey.py:538-545`
- [ ] 改写 `tests/test_advisory_request.py:106-114`（去掉 `created["customer_id"]` 断言）与 `:125-132`（改为断言伪造的 `customer_id` 后，这条请求出现在客户 A 的列表里、不出现在客户 B 的列表里）

**注意：** `/plans/{final_id}` 是全仓第一个客户侧「按 id 取自己资源」的接口。`/plan` 靠 `auth.subject_id` 天然圈定范围，这个不靠，越权检查必须显式写。
