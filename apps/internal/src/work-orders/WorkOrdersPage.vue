<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { PageHeader, PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { listAllCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import { formatDateTime } from "../format";
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
 *
 * 列表分页与筛选都由服务端说话（ADR-0024）：筛选条件与页码一起交给接口，「共 N 条」
 * 是过滤后的总数。客户筛选的下拉是例外——它要的是**全部**客户，不是这一页
 * （`listAllCustomers`），否则第 101 位客户在选中框里根本不存在。
 */
const router = useRouter();
const auth = useAuthStore();

const statusFilter = ref<WorkOrderStatus | "">("");
const customerFilter = ref<number | null>(null);
const alertFilter = ref<number | null>(null);

const {
  items: workOrders,
  total,
  page,
  pageSize,
  loading,
  errorMessage: loadError,
  goTo,
  reset,
} = usePagination<WorkOrder>(
  (query) =>
    listWorkOrders(
      {
        status: statusFilter.value || undefined,
        customerId: customerFilter.value ?? undefined,
        alertId: alertFilter.value ?? undefined,
      },
      query,
    ),
  { failureMessage: "工单列表加载失败" },
);

const customers = ref<CustomerListItem[]>([]);
const showCreate = ref(false);

const isRiskOfficer = computed(() => canCreateWorkOrder(auth.currentEmployee?.employee_role));

const customerLabel = computed(
  () =>
    customers.value.find((customer) => customer.id === customerFilter.value)?.real_name ?? "不限",
);

async function loadCustomers(): Promise<void> {
  // 客户筛选的下拉要的是完整目录，不是某一页：目录本身按页给（ADR-0024），
  // 这里的取数把页翻完再拼（`listAllCustomers`）。
  try {
    customers.value = await listAllCustomers();
  } catch {
    customers.value = [];
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
  // 新单按建单时间倒序排在最前，回第一页才看得到它：停在原来的第 3 页上，
  // 建完单看起来「什么都没发生」。
  await reset();
}

// 改筛选是「换了一批数据」，回到第一页重取：停在第 3 页会看到「筛选后为空」，
// 而那不是筛选的结果，是页码的。
watch([statusFilter, customerFilter, alertFilter], reset);

onMounted(async () => {
  await Promise.all([loadCustomers(), reset()]);
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
        // 过滤后的总数，不是本页条数：分页一开，本页条数会随翻页变。
        label: "工单总数",
        value: `共 ${total.value} 条`,
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
      <form class="filters" data-testid="work-order-filters" @submit.prevent="reset">
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
