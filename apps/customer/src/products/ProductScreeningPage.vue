<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError, PageHeader, PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { submitAdvisoryRequest } from "../advisory/api";
import ProductDetailPanel from "./ProductDetailPanel.vue";
import { compactFilters, getCandidatePool, getProduct, listProducts } from "./api";
import {
  SUITABILITY_EXPIRED,
  SUITABILITY_UNAVAILABLE,
  SUITABILITY_UNKNOWN,
  describeSuitability,
} from "./suitability";
import { PRODUCT_RISK_LEVELS, type Product, type ProductFilters } from "./types";

// 「这是符合条件的产品清单，不是推荐」常驻，不因结果条数变化而隐藏（ADR-0005）。
const DISCLAIMER = "这是符合条件的产品清单，不是推荐";
const EMPTY_HINT =
  "没有符合条件的产品。条件可能过严，可放宽产品类型、提高可接受的起投金额，或下调业绩基准后再筛选。";

const PRODUCT_TYPES = ["货币基金", "债券基金", "混合基金", "股票基金"] as const;

const filters = reactive<ProductFilters>({
  product_type: "",
  risk_level: "",
  min_amount: "",
  min_expected_return: "",
  max_term_days: "",
});

const selected = ref<Product | null>(null);
const detailError = ref("");
// 详情面板挂在清单下方，需要被滚进视野才能算作「点了有反应」。
const detailPanel = ref<HTMLElement | null>(null);

// 适当性说明：可购范围只能由后端给出，前端不自行推断。
const suitabilityNote = ref("");

const advisoryError = ref("");
const advisorySubmitting = ref(false);

const router = useRouter();

/**
 * 产品清单的一页（ADR-0024），排序恒为 `product_code` 升序（ADR-0005）——分页只是
 * 在这条固定顺序上切片，筛选条件在取数闭包里每次现读，改完条件调 `applyFilters()`
 * 回到第一页重取。
 */
const {
  items: products,
  total: productsTotal,
  page: productsPage,
  pageSize: productsPageSize,
  loading,
  errorMessage,
  goTo: goToProductsPage,
  reset: resetProducts,
} = usePagination<Product>(
  async (query) => {
    try {
      return await listProducts(query, filters);
    } catch (error) {
      // 未完成风险测评时可购范围无法确定：这一句比服务端的原始 404 文案更明确该做什么。
      if (error instanceof ApiError && error.code === 404) {
        throw new ApiError({
          code: error.code,
          message: SUITABILITY_UNAVAILABLE,
          data: null,
          trace_id: error.traceId,
        });
      }
      throw error;
    }
  },
  { failureMessage: "产品清单加载失败" },
);

async function applyFilters(): Promise<void> {
  selected.value = null;
  await resetProducts();
}

async function loadSuitability(): Promise<void> {
  try {
    suitabilityNote.value = describeSuitability(await getCandidatePool());
  } catch (error) {
    if (error instanceof ApiError && error.code === 403) {
      suitabilityNote.value = SUITABILITY_EXPIRED;
    } else if (error instanceof ApiError && error.code === 404) {
      suitabilityNote.value = SUITABILITY_UNAVAILABLE;
    } else {
      suitabilityNote.value = SUITABILITY_UNKNOWN;
    }
  }
}

async function openDetail(product: Product): Promise<void> {
  detailError.value = "";
  try {
    selected.value = await getProduct(product.product_code);
  } catch {
    detailError.value = "产品详情加载失败";
    selected.value = product;
  }
  // 面板出现在清单下方，长清单里它常常正好落在视口之外——滚进视野，点击才有可见反馈。
  // block: nearest：面板已完整可见就不动，避免每次点击都跳页。
  await nextTick();
  detailPanel.value?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function requestAdvisory(): Promise<void> {
  advisoryError.value = "";
  advisorySubmitting.value = true;
  try {
    await submitAdvisoryRequest(compactFilters(filters));
    // 提交完就知道该去哪里看结果：请求进度与已放行方案都在「我的方案」页。
    await router.push({ name: "advisory" });
  } catch (error) {
    advisoryError.value = error instanceof ApiError ? error.message : "方案请求提交失败";
  } finally {
    advisorySubmitting.value = false;
  }
}

onMounted(async () => {
  await Promise.all([resetProducts(), loadSuitability()]);
});
</script>

<template>
  <div class="screening">
    <PageHeader title="产品筛选" :breadcrumb="['客户视图', '产品筛选']" />

    <PanelCard title="筛选条件">
      <p class="screening__disclaimer" data-testid="not-recommendation">{{ DISCLAIMER }}</p>

      <form class="filters" @submit.prevent="applyFilters">
        <label class="filters__field">
          <span class="filters__label">产品类型</span>
          <el-select v-model="filters.product_type" name="product_type" placeholder="全部">
            <el-option label="全部" value="" />
            <el-option v-for="type in PRODUCT_TYPES" :key="type" :label="type" :value="type" />
          </el-select>
        </label>

        <label class="filters__field">
          <span class="filters__label">产品风险等级</span>
          <el-select v-model="filters.risk_level" name="risk_level" placeholder="全部">
            <el-option label="全部" value="" />
            <el-option v-for="level in PRODUCT_RISK_LEVELS" :key="level" :label="level" :value="level" />
          </el-select>
        </label>

        <label class="filters__field">
          <span class="filters__label">期限（天，上限）</span>
          <el-input v-model="filters.max_term_days" name="max_term_days" inputmode="numeric" placeholder="不限" />
        </label>

        <label class="filters__field">
          <span class="filters__label">起投金额（上限）</span>
          <el-input v-model="filters.min_amount" name="min_amount" inputmode="decimal" placeholder="不限" />
        </label>

        <label class="filters__field">
          <span class="filters__label">业绩基准（下限）</span>
          <el-input
            v-model="filters.min_expected_return"
            name="min_expected_return"
            inputmode="decimal"
            placeholder="不限"
          />
        </label>

        <el-button name="apply-filters" native-type="submit" :loading="loading">筛选</el-button>
      </form>
    </PanelCard>

    <PanelCard title="符合条件的产品">
      <p class="screening__suitability" data-testid="suitability-note">{{ suitabilityNote }}</p>

      <p v-if="errorMessage" class="screening__error" role="alert" data-testid="products-error">
        {{ errorMessage }}
      </p>
      <p v-else-if="!loading && products.length === 0" class="screening__empty" data-testid="empty-hint">
        {{ EMPTY_HINT }}
      </p>

      <div v-if="products.length" class="table-wrap">
        <table data-testid="products-table">
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>类型</th>
              <th>产品风险等级</th>
              <th>业绩基准</th>
              <th>期限（天）</th>
              <th>起投金额（元）</th>
              <th>费率（%）</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="product in products"
              :key="product.product_code"
              :data-product-code="product.product_code"
            >
              <td>{{ product.product_code }}</td>
              <td>{{ product.product_name }}</td>
              <td>{{ product.product_type }}</td>
              <td>{{ product.risk_level }}</td>
              <td>{{ product.expected_return }}</td>
              <td>{{ product.term_days }}</td>
              <td>{{ product.min_amount }}</td>
              <td>{{ product.fee_rate }}</td>
              <td>
                <el-button
                  size="small"
                  data-testid="product-detail-entry"
                  :name="`detail-${product.product_code}`"
                  @click="openDetail(product)"
                >
                  查看
                </el-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 取不到或空筛选结果时 `total` 归零，分页条与列表同进同退。 -->
      <PaginationBar
        v-if="productsTotal > 0"
        :total="productsTotal"
        :page="productsPage"
        :page-size="productsPageSize"
        :disabled="loading"
        @update:page="goToProductsPage"
      />

      <div class="screening__actions">
        <el-button name="request-advisory" :loading="advisorySubmitting" @click="requestAdvisory">
          请顾问出具方案
        </el-button>
      </div>

      <p v-if="advisoryError" class="screening__error" role="alert" data-testid="advisory-error">
        {{ advisoryError }}
      </p>
    </PanelCard>

    <div v-if="selected" ref="detailPanel">
      <ProductDetailPanel :product="selected" :error="detailError" />
    </div>
  </div>
</template>

<style scoped>
.screening {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.screening__disclaimer {
  margin: 0 0 var(--wm-space-4);
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 说明块左侧 3px 强调条（02 的 .note），颜色走令牌 */
  border-left: 3px solid var(--wm-color-primary);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  color: var(--wm-text-primary);
  font-size: 0.85rem;
}

.screening__suitability {
  margin: 0 0 var(--wm-space-4);
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.75;
}

.screening__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.screening__empty {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.75;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--wm-space-3) var(--wm-space-4);
}

.filters__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: calc(var(--wm-space-6) * 5);
}

.filters__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.filters :deep(.el-select) {
  width: 100%;
}

.screening__actions {
  margin-top: var(--wm-space-4);
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 表格行的 1px 分隔细线（令牌纪律声明的极少数例外） */
  border-bottom: 1px solid var(--wm-border-hairline);
  text-align: left;
  font-size: 0.85rem;
  white-space: nowrap;
}

th {
  color: var(--wm-text-muted);
  font-weight: 600;
}

td {
  color: var(--wm-text-primary);
  font-variant-numeric: tabular-nums;
}
</style>
