<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { PageHeader, PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { listAllCustomers, listCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import CustomerAdviceSection from "../operation-advice/CustomerAdviceSection.vue";
import { actionButton } from "../shell/actionButton";
import { useTopbarActions } from "../shell/pageSlots";
import OpenAccountForm from "./OpenAccountForm.vue";

/**
 * 客户关系（本 slice 从占位页实做）：名下客户列表 + 发起操作建议 + 开户。
 * 模块描述里删掉了「服务记录」——后端没有这个接口，界面不承诺它。
 * 这个模块没有检查器，第三栏塌成两栏。
 *
 * 列表翻页由服务端说话（ADR-0024）。下面「操作建议」那一段的选中框要的是**全部**客户，
 * 不是这一页：它拿的是完整目录（`listAllCustomers`），否则第 2 页之后的人就选不到了。
 */
const {
  items: customers,
  total,
  page,
  pageSize,
  loading,
  errorMessage: loadError,
  goTo,
  refresh: refreshCustomers,
  reset,
} = usePagination<CustomerListItem>((query) => listCustomers(query), {
  failureMessage: "名下客户加载失败",
});

const adviceCustomers = ref<CustomerListItem[]>([]);

async function loadAdviceCustomers(): Promise<void> {
  try {
    adviceCustomers.value = await listAllCustomers();
  } catch {
    // 目录拉不到不该挡住列表本身：建议区的选中框空着，列表照常翻页。
    adviceCustomers.value = [];
  }
}

async function load(): Promise<void> {
  await Promise.all([reset(), loadAdviceCustomers()]);
}

/** 刷新读的是屏幕上这两处：列表停在当前页，选中框重新对齐一次目录。 */
async function refresh(): Promise<void> {
  await Promise.all([refreshCustomers(), loadAdviceCustomers()]);
}

async function onCreated(): Promise<void> {
  ElMessage.success("已开户");
  // 以服务端为准重新拉一次：新客户是否落到我名下、排在第几页由后端决定。
  await load();
}

useTopbarActions(() => ({
  component: actionButton({
    label: "刷新",
    name: "refresh-customers",
    onClick: () => void refresh(),
  }),
}));

onMounted(load);
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

      <!-- 取不到时 `total` 归零，分页条与表格同进同退；越界页 `items` 为空但 `total`
           不变，所以它仍然留着——撤掉它，人就困在那一页上。 -->
      <PaginationBar
        v-if="total > 0"
        :total="total"
        :page="page"
        :page-size="pageSize"
        :disabled="loading"
        @update:page="goTo"
      />
    </PanelCard>

    <CustomerAdviceSection :customers="adviceCustomers" />

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
