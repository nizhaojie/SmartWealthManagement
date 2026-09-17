<script setup lang="ts">
import { onMounted, ref } from "vue";
import { SectionCard } from "@wealth/shared";
import {
  getCustomerAssets,
  getCustomerProfile,
  listCustomers,
  listRiskAssessments,
  writeProfileTag,
} from "./api";
import ProfilePanel from "./ProfilePanel.vue";
import type { CustomerListItem, CustomerProfileView, Holding, RiskAssessmentRecord } from "./types";

const customers = ref<CustomerListItem[]>([]);
const selectedId = ref<number | null>(null);
const profile = ref<CustomerProfileView | null>(null);
const assessments = ref<RiskAssessmentRecord[]>([]);
const holdings = ref<Holding[]>([]);
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
    const [nextProfile, nextAssessments, nextAssets] = await Promise.all([
      getCustomerProfile(customerId),
      listRiskAssessments(customerId),
      getCustomerAssets(customerId),
    ]);
    profile.value = nextProfile;
    assessments.value = nextAssessments;
    holdings.value = nextAssets.holdings;
  } catch (error) {
    profile.value = null;
    assessments.value = [];
    holdings.value = [];
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
    <SectionCard title="客户" class="profile-workspace__list">
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
    </SectionCard>
    <ProfilePanel
      v-if="profile"
      :profile="profile"
      :assessments="assessments"
      :holdings="holdings"
      @correct="correctTag"
    />
    <p v-else-if="!loadError" class="profile-workspace__empty">选择一位客户查看画像</p>
  </div>
</template>

<style scoped>
.profile-workspace {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: var(--wm-space-5);
  min-height: 70vh;
}

.profile-workspace__list button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
  margin-bottom: var(--wm-space-2);
  padding: var(--wm-space-2);
  background: none;
  border: 0;
  /* 3px 左指示条：激活态标记，同 AppShell 导航与 StatCard 左条规格 */
  border-left: 3px solid transparent;
  border-radius: var(--wm-radius-sm);
  cursor: pointer;
  text-align: left;
  color: var(--wm-text-primary);
}

.profile-workspace__list button.is-active {
  border-left-color: var(--wm-color-primary);
  background: var(--wm-color-primary-tint);
}

.profile-workspace__list span {
  color: var(--wm-text-muted);
  font-size: 12px;
}

.profile-workspace__error {
  color: var(--wm-color-danger);
}

.profile-workspace__empty {
  align-self: center;
  color: var(--wm-text-muted);
}

@media (max-width: 720px) {
  .profile-workspace {
    grid-template-columns: 1fr;
  }
}
</style>
