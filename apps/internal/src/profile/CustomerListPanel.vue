<script setup lang="ts">
import { ref } from "vue";
import { PaginationBar, PanelCard } from "@wealth/shared";
import type { CustomerListItem } from "../customers/types";

/**
 * 客户列表：只负责选人，画像怎么画是主体那一半的事。
 *
 * 关键字的筛选与翻页都在服务端（ADR-0024）：目录分页之后这里手里只有一页，本地过滤
 * 只过滤得动这一页——筛掉的人仍然在同一个接口的下一页里。输入框因此留一份草稿，按下
 * 查询（或回车）才交出去，交出去之后由页面回到第一页重取。
 */
const props = defineProps<{
  customers: CustomerListItem[];
  selectedId: number | null;
  loading: boolean;
  error: string;
  /** 过滤后的客户总数，由服务端给。 */
  total: number;
  page: number;
  pageSize: number;
  /** 已经在生效的关键字。 */
  keyword: string;
}>();

const emit = defineEmits<{
  select: [customerId: number];
  "update:page": [page: number];
  "update:keyword": [keyword: string];
}>();

const draft = ref(props.keyword);

function applyKeyword(): void {
  emit("update:keyword", draft.value.trim());
}
</script>

<template>
  <PanelCard title="客户">
    <form class="search" data-testid="customer-search" @submit.prevent="applyKeyword">
      <el-input
        v-model="draft"
        name="customer-keyword"
        placeholder="按姓名或账号过滤"
        class="search__input"
      />
      <el-button native-type="submit" name="search-customers" :loading="loading">查询</el-button>
    </form>

    <p v-if="error" class="list__error" role="alert" data-testid="customer-list-error">
      {{ error }}
    </p>
    <p v-else-if="loading" class="list__hint">加载中…</p>
    <p v-else-if="!customers.length" class="list__hint" data-testid="customer-list-empty">
      没有匹配的客户。
    </p>

    <ul v-else class="list">
      <li v-for="customer in customers" :key="customer.id">
        <button
          type="button"
          class="list__item"
          :class="{ 'list__item--active': customer.id === selectedId }"
          :name="`customer-${customer.id}`"
          :data-testid="`customer-${customer.id}`"
          @click="emit('select', customer.id)"
        >
          <strong class="list__name">{{ customer.real_name }}</strong>
          <span class="list__meta">
            {{ customer.risk_level ?? "未评测" }} · {{ customer.customer_level }}
          </span>
        </button>
      </li>
    </ul>

    <!-- 取不到时 `total` 归零，分页条与列表同进同退；越界页 `items` 为空但 `total`
         不变，所以它仍然留着——撤掉它，人就困在那一页上。 -->
    <PaginationBar
      v-if="total > 0"
      :total="total"
      :page="page"
      :page-size="pageSize"
      :disabled="loading"
      @update:page="emit('update:page', $event)"
    />
  </PanelCard>
</template>

<style scoped>
.search {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
  margin-bottom: var(--wm-space-3);
}

.search__input {
  flex: 1;
  min-width: 0;
}

.list {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: calc(var(--wm-space-6) * 14);
  overflow-y: auto;
}

.list__item {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  width: 100%;
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 细边框属令牌纪律声明的极少数 1px 例外；常态透明，只为 hover 时不让内容位移 */
  border: 1px solid transparent;
  border-radius: var(--wm-radius-sm);
  background-color: transparent;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.list__item:hover {
  background-color: var(--wm-bg-page);
}

/* 激活项是淡染底：底上的文字走 primary-strong */
.list__item--active {
  background-color: var(--wm-color-primary-tint);
}

.list__item--active .list__name {
  color: var(--wm-color-primary-strong);
}

.list__name {
  color: var(--wm-text-primary);
  font-size: 0.88rem;
  font-weight: 600;
}

.list__meta {
  color: var(--wm-text-muted);
  font-size: 0.78rem;
}

.list__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.list__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
