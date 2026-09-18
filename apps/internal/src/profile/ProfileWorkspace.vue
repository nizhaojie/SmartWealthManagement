<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { PageHeader } from "@wealth/shared";
import { errorMessage } from "../format";
import CustomerInspector from "../inspector/CustomerInspector.vue";
import { actionButton } from "../shell/actionButton";
import { useInspector, useTopbarActions } from "../shell/pageSlots";
import { useCurrentCustomerStore } from "../stores/currentCustomer";
import { listCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import { getCustomerAssets, getCustomerProfile, listRiskAssessments, writeProfileTag } from "./api";
import CustomerListPanel from "./CustomerListPanel.vue";
import ProfileMain from "./ProfileMain.vue";
import type { CustomerAssets, CustomerProfileView, RiskAssessmentRecord } from "./types";

/**
 * 客户画像：左侧客户列表 + 右侧画像主体。第三栏常驻客户检查器，
 * 选人即把「当前客户」写进全局 store，检查器跟着换。
 */
const currentCustomer = useCurrentCustomerStore();

const customers = ref<CustomerListItem[]>([]);
const customersLoading = ref(true);
const customersError = ref("");

const profile = ref<CustomerProfileView | null>(null);
const assessments = ref<RiskAssessmentRecord[]>([]);
const assets = ref<CustomerAssets | null>(null);
const profileLoading = ref(false);
const profileError = ref("");

const selectedId = ref<number | null>(null);

async function loadCustomers(): Promise<void> {
  customersLoading.value = true;
  customersError.value = "";
  try {
    customers.value = await listCustomers();
  } catch (error) {
    customersError.value = errorMessage(error, "客户列表加载失败");
  } finally {
    customersLoading.value = false;
  }
}

async function selectCustomer(customerId: number): Promise<void> {
  selectedId.value = customerId;
  currentCustomer.setCustomer(customerId);
  profileLoading.value = true;
  profileError.value = "";
  try {
    const [nextProfile, nextAssessments, nextAssets] = await Promise.all([
      getCustomerProfile(customerId),
      listRiskAssessments(customerId),
      getCustomerAssets(customerId),
    ]);
    profile.value = nextProfile;
    assessments.value = nextAssessments;
    assets.value = nextAssets;
  } catch (error) {
    profile.value = null;
    assessments.value = [];
    assets.value = null;
    profileError.value = errorMessage(error, "画像加载失败");
  } finally {
    profileLoading.value = false;
  }
}

async function refresh(): Promise<void> {
  if (selectedId.value === null) {
    await loadCustomers();
    return;
  }
  await selectCustomer(selectedId.value);
}

async function correctTag(payload: {
  tagKey: string;
  value: unknown;
  reason: string;
}): Promise<void> {
  if (selectedId.value === null) return;
  try {
    // 后端返回刷新后的完整画像，直接替换，不本地改一份可能不一致的副本。
    profile.value = await writeProfileTag({
      customerId: selectedId.value,
      tagKey: payload.tagKey,
      value: payload.value,
      source: "理财顾问手工修正",
      reason: payload.reason,
    });
    ElMessage.success("已保存修正");
  } catch (error) {
    ElMessage.error(errorMessage(error, "修正失败"));
  }
}

// 页面往壳里注入自己的检查器与顶栏操作；离开这个页面时自动收回。
useInspector(() => ({ component: CustomerInspector }));
useTopbarActions(() => ({
  component: actionButton({ label: "刷新", name: "refresh-profile", onClick: () => void refresh() }),
}));

onMounted(loadCustomers);
</script>

<template>
  <div class="profile">
    <PageHeader title="客户画像" :breadcrumb="['客户画像']" />

    <div class="profile__grid">
      <CustomerListPanel
        :customers="customers"
        :selected-id="selectedId"
        :loading="customersLoading"
        :error="customersError"
        @select="selectCustomer"
      />

      <div class="profile__main">
        <p v-if="profileError" class="profile__error" role="alert" data-testid="profile-error">
          {{ profileError }}
        </p>
        <p v-else-if="!profile" class="profile__empty" data-testid="profile-empty">
          选择一位客户查看画像
        </p>
        <ProfileMain
          v-else
          :profile="profile"
          :assessments="assessments"
          :holdings="assets?.holdings ?? []"
          :loading="profileLoading"
          @correct="correctTag"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.profile__grid {
  display: grid;
  grid-template-columns: calc(var(--wm-space-6) * 8) minmax(0, 1fr);
  gap: var(--wm-space-4);
  align-items: start;
}

@media (max-width: 1280px) {
  .profile__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.profile__main {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  min-width: 0;
}

.profile__empty {
  margin: 0;
  padding: var(--wm-space-6);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px dashed var(--wm-border);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-card);
  color: var(--wm-text-muted);
  font-size: 0.9rem;
  text-align: center;
}

.profile__error {
  margin: 0;
  padding: var(--wm-space-4);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-color-danger);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-card);
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
