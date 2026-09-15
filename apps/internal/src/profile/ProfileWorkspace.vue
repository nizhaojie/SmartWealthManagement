<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getCustomerProfile, listCustomers, listRiskAssessments, writeProfileTag } from "./api";
import ProfilePanel from "./ProfilePanel.vue";
import type { CustomerListItem, CustomerProfileView, RiskAssessmentRecord } from "./types";

const customers = ref<CustomerListItem[]>([]);
const selectedId = ref<number | null>(null);
const profile = ref<CustomerProfileView | null>(null);
const assessments = ref<RiskAssessmentRecord[]>([]);
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
    const [nextProfile, nextAssessments] = await Promise.all([
      getCustomerProfile(customerId),
      listRiskAssessments(customerId),
    ]);
    profile.value = nextProfile;
    assessments.value = nextAssessments;
  } catch (error) {
    profile.value = null;
    assessments.value = [];
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
    <ProfilePanel
      v-if="profile"
      :profile="profile"
      :assessments="assessments"
      @correct="correctTag"
    />
    <p v-else-if="!loadError" class="profile-workspace__empty">选择一位客户查看画像</p>
  </div>
</template>

<style scoped>
.profile-workspace {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 20px;
  min-height: 70vh;
  --blotter: #10263a;
  --paper: #f3f6f8;
}

.profile-workspace__list {
  background: white;
  padding: 16px;
  border-top: 3px solid var(--blotter);
}

.profile-workspace__list h2 {
  margin: 0 0 12px;
  font-size: 12px;
  letter-spacing: 0.2em;
  color: var(--blotter);
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
  border-left-color: #9a7b4f;
  background: var(--paper);
}

.profile-workspace__list span {
  color: #5c6570;
  font-size: 12px;
}

.profile-workspace__error {
  color: #b42318;
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
