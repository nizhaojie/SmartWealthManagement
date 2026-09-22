# 09 — 产品筛选分页

**What to build:** 客户产品筛选列表分页，排序键沿用 `product_code` 升序（ADR-0005），分页不得破坏这条硬性排序。

**Blocked by:** 02 — 统一分页机制 + 交易流水端到端

**Status:** ready-for-agent

- [ ] `products` 接口接收 `page`/`page_size`，返回 `{items, total, page, page_size}`
- [ ] 排序保持 `product_code` 升序（ADR-0005），分页切片不影响排序稳定性
- [ ] `ProductScreeningPage` 接 `PaginationBar`，筛选条件翻页保留
- [ ] 断言：翻页不重不漏、`total` 正确、排序仍按产品代码升序

**实现落点：** `backend/app/api/products.py` 与 `app/product_screening/service.py`（`list_products` 加分页），`apps/customer/src/products/ProductScreeningPage.vue`，后端 HTTP 测试与前端 spec。

**验收：** 产品超过一页可翻页，且始终按产品代码升序、不按收益率排序（护栏测试 4 的 seam 保持）。
