<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ApiError } from "@wealth/shared";
import { getProduct, listProducts } from "./api";
import type { Product, ProductFilters } from "./types";

const DISCLAIMER = "这是符合条件的产品清单，不是推荐";
const EMPTY_HINT =
  "没有符合条件的产品。条件可能过严，可放宽产品类型、提高可接受的起投金额，或下调业绩基准后再筛选。";

const PRODUCT_TYPES = ["货币基金", "债券基金", "混合基金", "股票基金"] as const;
const PRODUCT_RISK_LEVELS = ["R1", "R2", "R3", "R4", "R5"] as const;

const filters = reactive<ProductFilters>({
  product_type: "",
  risk_level: "",
  min_amount: "",
  min_expected_return: "",
  max_term_days: "",
});

const products = ref<Product[]>([]);
const loading = ref(true);
const errorMessage = ref("");
const selected = ref<Product | null>(null);
const detailError = ref("");

function filledFilters(): ProductFilters {
  const next: ProductFilters = {};
  if (filters.product_type) next.product_type = filters.product_type;
  if (filters.risk_level) next.risk_level = filters.risk_level;
  if (filters.min_amount) next.min_amount = filters.min_amount;
  if (filters.min_expected_return) next.min_expected_return = filters.min_expected_return;
  if (filters.max_term_days) next.max_term_days = filters.max_term_days;
  return next;
}

async function loadProducts() {
  loading.value = true;
  errorMessage.value = "";
  selected.value = null;
  try {
    const payload = await listProducts(filledFilters());
    products.value = payload.products;
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : "产品清单加载失败";
    products.value = [];
  } finally {
    loading.value = false;
  }
}

async function openDetail(product: Product) {
  detailError.value = "";
  try {
    selected.value = await getProduct(product.product_code);
  } catch {
    detailError.value = "产品详情加载失败";
    selected.value = product;
  }
}

function requestAdvisory() {
  // 方案请求的提交与状态在下一张 ticket。
}

onMounted(loadProducts);
</script>

<template>
  <el-card>
    <h1>产品筛选</h1>
    <p data-testid="not-recommendation">{{ DISCLAIMER }}</p>

    <form @submit.prevent="loadProducts">
      <label>
        产品类型
        <select name="product_type" v-model="filters.product_type">
          <option value="">全部</option>
          <option v-for="type in PRODUCT_TYPES" :key="type" :value="type">{{ type }}</option>
        </select>
      </label>
      <label>
        产品风险等级
        <select name="risk_level" v-model="filters.risk_level">
          <option value="">全部</option>
          <option v-for="level in PRODUCT_RISK_LEVELS" :key="level" :value="level">{{ level }}</option>
        </select>
      </label>
      <label>
        期限（天，上限）
        <input name="max_term_days" v-model="filters.max_term_days" inputmode="numeric" />
      </label>
      <label>
        起投金额（上限）
        <input name="min_amount" v-model="filters.min_amount" inputmode="decimal" />
      </label>
      <label>
        业绩基准（下限）
        <input name="min_expected_return" v-model="filters.min_expected_return" inputmode="decimal" />
      </label>
      <el-button name="apply-filters" native-type="submit" :loading="loading">筛选</el-button>
    </form>

    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <p v-else-if="!loading && products.length === 0" data-testid="empty-hint">{{ EMPTY_HINT }}</p>

    <div v-if="products.length" class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>代码</th>
          <th>名称</th>
          <th>类型</th>
          <th>产品风险等级</th>
          <th>业绩基准</th>
          <th>期限</th>
          <th>起投金额</th>
          <th>费率</th>
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
            <button type="button" :name="`detail-${product.product_code}`" @click="openDetail(product)">
              查看
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    </div>

    <el-button name="request-advisory" @click="requestAdvisory">请顾问出具方案</el-button>

    <section v-if="selected" data-testid="product-detail">
      <h2>产品详情</h2>
      <p v-if="detailError" role="alert">{{ detailError }}</p>
      <dl>
        <div><dt>代码</dt><dd>{{ selected.product_code }}</dd></div>
        <div><dt>名称</dt><dd>{{ selected.product_name }}</dd></div>
        <div><dt>类型</dt><dd>{{ selected.product_type }}</dd></div>
        <div><dt>产品风险等级</dt><dd>{{ selected.risk_level }}</dd></div>
        <div><dt>业绩基准</dt><dd>{{ selected.expected_return }}</dd></div>
        <div><dt>期限</dt><dd>{{ selected.term_days }}</dd></div>
        <div><dt>起投金额</dt><dd>{{ selected.min_amount }}</dd></div>
        <div><dt>费率</dt><dd>{{ selected.fee_rate }}</dd></div>
        <div><dt>基金经理</dt><dd>{{ selected.fund_manager }}</dd></div>
      </dl>
    </section>
  </el-card>
</template>

<style scoped>
form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1rem;
  align-items: flex-end;
  margin: 1rem 0;
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
  text-align: left;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--el-border-color-lighter);
  white-space: nowrap;
}
</style>
