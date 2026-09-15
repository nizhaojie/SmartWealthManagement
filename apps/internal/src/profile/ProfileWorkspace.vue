<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getCustomerProfile, listCustomers, writeProfileTag } from "./api";
import ProfilePanel from "./ProfilePanel.vue";
import type { CustomerListItem, CustomerProfileView } from "./types";

const customers = ref<CustomerListItem[]>([]);
const selectedId = ref<number | null>(null);
const profile = ref<CustomerProfileView | null>(null);
const loadError = ref("");

async function loadCustomers() {
  loadError.value = "";
  try {
    customers.value = await listCustomers();
    if (customers.value.length && selectedId.value === null) {
      await selectCustomer(customers.value[0].id);
    }
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : "加载客户列表失败";
  }
}

async function selectCustomer(customerId: number) {
  selectedId.value = customerId;
  loadError.value = "";
  try {
    profile.value = await getCustomerProfile(customerId);
  } catch (error) {
    profile.value = null;
    loadError.value = error instanceof Error ? error.message : "加载客户画像失败";
  }
}

async function correctTag(payload: { tagKey: string; value: unknown; reason: string }) {
  if (selectedId.value === null) return;
  loadError.value = "";
  try {
    profile.value = await writeProfileTag({
      customerId: selectedId.value,
      tagKey: payload.tagKey,
      value: payload.value,
      source: "理财顾问手工修正",
      reason: payload.reason,
    });
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : "保存修正失败";
  }
}

onMounted(loadCustomers);
</script>

<template>
  <div class="profile-workspace">
    <aside class="profile-workspace__list">
      <h2>客户</h2>
      <p v-if="loadError" class="profile-workspace__error">{{ loadError }}</p>
      <button
        v-for="customer in customers"
        :key="customer.id"
        type="button"
        :class="{ 'is-active': customer.id === selectedId }"
        @click="selectCustomer(customer.id)"
      >
        <strong>{{ customer.real_name }}</strong>
        <span>{{ customer.risk_level ?? "未评测" }} · {{ customer.customer_level }}</span>
      </button>
    </aside>
    <ProfilePanel v-if="profile" :profile="profile" @correct="correctTag" />
    <p v-else-if="!loadError" class="profile-workspace__empty">选择一位客户查看画像</p>
  </div>
</template>

<style scoped>
.profile-workspace {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 20px;
  min-height: 70vh;
  --ink: #1b2a4a;
  --vellum: #f7f4ec;
}

.profile-workspace__list {
  background: #fffdf7;
  padding: 16px;
  border: 1px solid color-mix(in srgb, var(--ink) 12%, transparent);
}

.profile-workspace__list h2 {
  margin: 0 0 12px;
  font-size: 14px;
  letter-spacing: 0.16em;
}

.profile-workspace__list button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
  margin-bottom: 8px;
  padding: 10px 8px;
  background: none;
  border: 0;
  border-left: 3px solid transparent;
  cursor: pointer;
  text-align: left;
}

.profile-workspace__list button.is-active {
  border-left-color: #c4a35a;
  background: var(--vellum);
}

.profile-workspace__list span {
  color: #6b6560;
  font-size: 12px;
}

.profile-workspace__error {
  color: #9b2c2c;
}

.profile-workspace__empty {
  align-self: center;
}

@media (max-width: 720px) {
  .profile-workspace {
    grid-template-columns: 1fr;
  }
}
</style>
