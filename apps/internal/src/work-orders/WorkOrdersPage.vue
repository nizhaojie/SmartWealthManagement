<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { PageHeader, PanelCard } from "@wealth/shared";
import { listCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import { errorMessage, formatDateTime } from "../format";
import SummaryCard from "../inspector/SummaryCard.vue";
import { useInspector } from "../shell/pageSlots";
import { useAuthStore } from "../stores/auth";
import { listWorkOrders } from "./api";
import ExternalWorkOrderForm from "./ExternalWorkOrderForm.vue";
import { WORK_ORDER_STATUSES, type WorkOrder, type WorkOrderStatus } from "./types";
import { canCreateWorkOrder, workOrderTagType } from "./workOrderView";

/**
 * 工单管理：列表 + 外部建单 + 详情与流转。
 *
 * 工单从风控监测拆到一级模块后，「处置完预警去办工单」变成一次跨模块跳转，
 * 换来的是工单不再被当成预警的附属物。
 */
const router = useRouter();
const auth = useAuthStore();

const workOrders = ref<WorkOrder[]>([]);
const loading = ref(true);
const loadError = ref("");

const statusFilter = ref<WorkOrderStatus | "">("");
const customerFilter = ref<number | null>(null);
const alertFilter = ref<number | null>(null);

const customers = ref<CustomerListItem[]>([]);
const showCreate = ref(false);

const isRiskOfficer = computed(() => canCreateWorkOrder(auth.currentEmployee?.employee_role));

const customerLabel = computed(
  () =>
    customers.value.find((customer) => customer.id === customerFilter.value)?.real_name ?? "不限",
);

async function loadCustomers(): Promise<void> {
  try {
    customers.value = await listCustomers();
  } catch {
    customers.value = [];
  }
}

async function loadWorkOrders(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    workOrders.value = await listWorkOrders({
      status: statusFilter.value || undefined,
      customerId: customerFilter.value ?? undefined,
      alertId: alertFilter.value ?? undefined,
    });
  } catch (error) {
    workOrders.value = [];
    loadError.value = errorMessage(error, "工单列表加载失败");
  } finally {
    loading.value = false;
  }
}

function openDetail(workOrderId: number): void {
  void router.push({ name: "work-order-detail", params: { workOrderId } });
}

function toggleCreate(): void {
  showCreate.value = !showCreate.value;
}

async function onCreated(): Promise<void> {
  showCreate.value = false;
  await loadWorkOrders();
}

watch([statusFilter, customerFilter, alertFilter], loadWorkOrders);

onMounted(async () => {
  await Promise.all([loadCustomers(), loadWorkOrders()]);
});

// 注入模块自己的筛选摘要（右侧检查器）。
useInspector(() => ({
  component: SummaryCard,
  props: {
    title: "工单管理",
    rows: [
      {
        label: "筛选摘要",
        value: `状态 ${statusFilter.value || "全部"} · 客户 ${customerLabel.value} · 来源预警 ${
          alertFilter.value ?? "不限"
        }`,
        testId: "work-order-summary-filters",
      },
      {
        label: "当前列表",
        value: `${workOrders.value.length} 条`,
        testId: "work-order-summary-count",
      },
    ],
    note: "工单可来自预警处置，也可来自客户投诉与转人工。接单 / 办结 / 关闭只对风控专员开放。",
  },
}));

</script>

<template>
  <div class="work-orders">
    <PageHeader title="工单管理" :breadcrumb="['工单管理']" />

    <PanelCard title="筛选">
      <form class="filters" data-testid="work-order-filters" @submit.prevent="loadWorkOrders">
        <label class="filters__field">
          <span class="filters__label">状态</span>
          <el-select
            v-model="statusFilter"
            name="work-order-status"
            placeholder="全部"
            data-testid="work-order-status-filter"
          >
            <el-option label="全部" value="" />
            <el-option
              v-for="status in WORK_ORDER_STATUSES"
              :key="status"
              :label="status"
              :value="status"
            />
          </el-select>
        </label>

        <label class="filters__field">
          <span class="filters__label">客户</span>
          <el-select v-model="customerFilter" name="work-order-customer" clearable placeholder="全部">
            <el-option
              v-for="customer in customers"
              :key="customer.id"
              :label="customer.real_name"
              :value="customer.id"
            />
          </el-select>
        </label>

        <label class="filters__field">
          <span class="filters__label">来源预警编号</span>
          <el-input v-model.number="alertFilter" name="work-order-alert" placeholder="不限" />
        </label>

        <el-button name="apply-work-order-filters" native-type="submit" :loading="loading">
          查询
        </el-button>
      </form>
    </PanelCard>

    <ExternalWorkOrderForm v-if="showCreate" @created="onCreated" @collapse="toggleCreate" />

    <PanelCard title="工单列表">
      <template v-if="isRiskOfficer && !showCreate" #actions>
        <el-button name="toggle-create-work-order" @click="toggleCreate">
          创建外部工单
        </el-button>
      </template>
      <p v-if="loadError" class="work-orders__error" role="alert" data-testid="work-order-error">
        {{ loadError }}
      </p>
      <p v-else-if="!loading && !workOrders.length" class="work-orders__hint" data-testid="work-orders-empty">
        暂无工单
      </p>

      <!--
        列宽一律是「最小宽度」：el-table 只在各列最小宽度之和大于容器时才出横向滚动条，
        固定 width 还会让列在宽屏上一动不动。原先的固定值合计 1030px，比「1200px 视口 +
        侧栏展开 + 检查器收起」的可用宽度（873px）宽出 157px，于是那几种状态下总挂着水平滑动条。
        收到合计 862px，创建时间列给足 172px 让 `YYYY-MM-DD HH:mm:ss` 单行显示；
        宽度有余时由 el-table 按列分配，工单编号这类长串也能摊开成一行。
      -->
      <el-table v-if="workOrders.length" :data="workOrders" data-testid="work-orders-table">
        <el-table-column label="工单编号" prop="work_order_no" min-width="168" />
        <el-table-column label="来源" prop="order_type" min-width="80" />
        <el-table-column label="优先级" prop="priority" min-width="70" />
        <el-table-column label="状态" min-width="80">
          <template #default="{ row }">
            <el-tag :type="workOrderTagType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="受理人" min-width="72">
          <template #default="{ row }">{{ row.handler_name || "—" }}</template>
        </el-table-column>
        <el-table-column label="最近理由" min-width="134">
          <template #default="{ row }">{{ row.handle_reason ?? "—" }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="172">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="86">
          <template #default="{ row }">
            <el-button size="small" name="open-work-order" @click="openDetail(row.id)">处置</el-button>
          </template>
        </el-table-column>
      </el-table>
    </PanelCard>
  </div>
</template>

<style scoped>
.work-orders {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--wm-space-3) var(--wm-space-4);
}

.filters__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: calc(var(--wm-space-6) * 5);
}

.filters__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.work-orders__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.work-orders__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.7;
}
</style>
