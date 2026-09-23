<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { PageHeader, usePagination } from "@wealth/shared";
import { errorMessage } from "../format";
import CustomerInspector from "../inspector/CustomerInspector.vue";
import { actionButton } from "../shell/actionButton";
import { useInspector, useTopbarActions } from "../shell/pageSlots";
import { useCurrentCustomerStore } from "../stores/currentCustomer";
import { listCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import { getCustomerAssets, getCustomerProfile, writeProfileTag } from "./api";
import CustomerListPanel from "./CustomerListPanel.vue";
import ProfileMain from "./ProfileMain.vue";
import type { CustomerAssets, CustomerProfileView } from "./types";

/**
 * 客户画像：左侧客户列表 + 右侧画像主体。第三栏常驻客户检查器，
 * 选人即把「当前客户」写进全局 store，检查器跟着换。
 */
const currentCustomer = useCurrentCustomerStore();

// 关键字与页码都由服务端说话（ADR-0024）：取数闭包每次现读关键字，改完关键字 `reset()`
// 回到第一页重取——停在第 3 页会看到「筛完就这几条」，而那不是筛选的结果，是页码的。
const keyword = ref("");

const {
  items: customers,
  total: customerTotal,
  page: customerPage,
  pageSize: customerPageSize,
  loading: customersLoading,
  errorMessage: customersError,
  goTo: goToCustomerPage,
  refresh: refreshCustomers,
  reset: resetCustomers,
} = usePagination<CustomerListItem>(
  (query) => listCustomers(query, { keyword: keyword.value || undefined }),
  { failureMessage: "客户列表加载失败" },
);

watch(keyword, () => {
  void resetCustomers();
});

const profile = ref<CustomerProfileView | null>(null);
const assets = ref<CustomerAssets | null>(null);
const profileLoading = ref(false);
const profileError = ref("");

const selectedId = ref<number | null>(null);

async function selectCustomer(customerId: number): Promise<void> {
  selectedId.value = customerId;
  currentCustomer.setCustomer(customerId);
  profileLoading.value = true;
  profileError.value = "";
  try {
    const [nextProfile, nextAssets] = await Promise.all([
      getCustomerProfile(customerId),
      getCustomerAssets(customerId),
    ]);
    profile.value = nextProfile;
    assets.value = nextAssets;
  } catch (error) {
    profile.value = null;
    assets.value = null;
    profileError.value = errorMessage(error, "画像加载失败");
  } finally {
    profileLoading.value = false;
  }
}

async function refresh(): Promise<void> {
  if (selectedId.value === null) {
    // 没选人时刷新的是客户列表本身，停在当前这一页（回到第一页不是「刷新」的意思）。
    await refreshCustomers();
    return;
  }
  await selectCustomer(selectedId.value);
  // 历次评测不跟着重读：它是只追加的留痕，且自己有翻页控件，重读只会把页码打回第一页。
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

onMounted(() => {
  void resetCustomers();
});
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
        :total="customerTotal"
        :page="customerPage"
        :page-size="customerPageSize"
        :keyword="keyword"
        @select="selectCustomer"
        @update:page="goToCustomerPage"
        @update:keyword="keyword = $event"
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
          :risk-valid-until="assets?.risk_level_valid_until ?? null"
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
