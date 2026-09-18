<script setup lang="ts">
import { computed, ref } from "vue";
import { PanelCard } from "@wealth/shared";
import type { CustomerListItem } from "../customers/types";

// 客户列表：只负责选人，画像怎么画是主体那一半的事。
const props = defineProps<{
  customers: CustomerListItem[];
  selectedId: number | null;
  loading: boolean;
  error: string;
}>();

const emit = defineEmits<{ select: [customerId: number] }>();

const keyword = ref("");

const filtered = computed(() => {
  const text = keyword.value.trim();
  if (!text) return props.customers;
  return props.customers.filter(
    (customer) => customer.real_name.includes(text) || customer.username.includes(text),
  );
});
</script>

<template>
  <PanelCard title="客户">
    <el-input
      v-model="keyword"
      name="customer-keyword"
      placeholder="按姓名或账号过滤"
      class="list__search"
    />

    <p v-if="error" class="list__error" role="alert" data-testid="customer-list-error">
      {{ error }}
    </p>
    <p v-else-if="loading" class="list__hint">加载中…</p>
    <p v-else-if="!filtered.length" class="list__hint" data-testid="customer-list-empty">
      没有匹配的客户。
    </p>

    <ul v-else class="list">
      <li v-for="customer in filtered" :key="customer.id">
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
  </PanelCard>
</template>

<style scoped>
.list__search {
  margin-bottom: var(--wm-space-3);
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
