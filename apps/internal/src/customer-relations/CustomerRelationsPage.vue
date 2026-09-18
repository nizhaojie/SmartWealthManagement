<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { PageHeader, PanelCard } from "@wealth/shared";
import { listCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import { errorMessage } from "../format";
import { actionButton } from "../shell/actionButton";
import { useTopbarActions } from "../shell/pageSlots";
import OpenAccountForm from "./OpenAccountForm.vue";

/**
 * 客户关系（本 slice 从占位页实做）：名下客户列表 + 开户。
 * 模块描述里删掉了「服务记录」——后端没有这个接口，界面不承诺它。
 * 这个模块没有检查器，第三栏塌成两栏。
 */
const customers = ref<CustomerListItem[]>([]);
const loading = ref(true);
const loadError = ref("");

async function loadCustomers(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    customers.value = await listCustomers();
  } catch (error) {
    customers.value = [];
    loadError.value = errorMessage(error, "名下客户加载失败");
  } finally {
    loading.value = false;
  }
}

async function onCreated(): Promise<void> {
  ElMessage.success("已开户");
  // 以服务端为准重新拉一次：新客户是否落到我名下由后端决定。
  await loadCustomers();
}

useTopbarActions(() => ({
  component: actionButton({
    label: "刷新",
    name: "refresh-customers",
    onClick: () => void loadCustomers(),
  }),
}));

onMounted(loadCustomers);
</script>

<template>
  <div class="relations">
    <PageHeader title="客户关系" :breadcrumb="['客户关系']" />

    <PanelCard title="名下客户">
      <p v-if="loadError" class="relations__error" role="alert" data-testid="relations-error">
        {{ loadError }}
      </p>
      <p v-else-if="!loading && !customers.length" class="relations__empty" data-testid="relations-empty">
        名下还没有客户。可以在下面直接开户。
      </p>

      <el-table v-if="customers.length" :data="customers" data-testid="relations-table">
        <el-table-column label="姓名" prop="real_name" min-width="120" />
        <el-table-column label="登录账号" prop="username" min-width="140" />
        <el-table-column label="客户分层" prop="customer_level" width="110" />
        <el-table-column label="风险承受等级" width="130">
          <template #default="{ row }">{{ row.risk_level ?? "未评测" }}</template>
        </el-table-column>
      </el-table>
    </PanelCard>

    <OpenAccountForm @created="onCreated" />
  </div>
</template>

<style scoped>
.relations {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.relations__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.relations__empty {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}
</style>
