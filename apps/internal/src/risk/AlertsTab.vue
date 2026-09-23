<script setup lang="ts">
// 预警列表：筛选、排序与分页都由服务端执行（ADR-0024）。
//
// 排序原来是在这里对本页数据做的（`sortAlerts`）。分页之后前端手里只有当前页，
// 本地排序会让「按等级（重到轻）」只在这一页内成立、翻页即乱——所以排序方式改成
// 一个查询参数，由服务端连同筛选一起算出这一页该是哪几条。
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { formatDateTime } from "../format";
import { listAlerts } from "./api";
import {
  ALERT_LEVELS,
  ALERT_STATUSES,
  type AlertLevel,
  type AlertOrder,
  type AlertStatus,
  type AlertSummary,
} from "./types";
import {
  ALERT_SORT_OPTIONS,
  confidenceText,
  levelTagType,
  statusTagType,
  type TabSummary,
} from "./riskView";
import { workOrderTagType } from "../work-orders/workOrderView";
import { useTabSummary } from "./useTabSummary";

const emit = defineEmits<{ summary: [value: TabSummary] }>();

const router = useRouter();

const levelFilter = ref<AlertLevel | "">("");
const statusFilter = ref<AlertStatus | "">("");
const dateRange = ref<[string, string] | null>(null);
const sortBy = ref<AlertOrder>("created_desc");

const rangeLabel = computed(() =>
  dateRange.value ? `${dateRange.value[0]} ~ ${dateRange.value[1]}` : "不限",
);

function isoFrom(date: string, endOfDay: boolean): string {
  return new Date(`${date}T${endOfDay ? "23:59:59" : "00:00:00"}`).toISOString();
}

// 取数闭包每次现读筛选与排序：`reset()` 回到第一页再取，取到的就是新条件的第一页。
const {
  items,
  total,
  page,
  pageSize,
  loading,
  errorMessage: alertError,
  goTo,
  reset,
} = usePagination<AlertSummary>(
  (query) =>
    listAlerts(
      {
        alertLevel: levelFilter.value || undefined,
        status: statusFilter.value || undefined,
        createdFrom: dateRange.value ? isoFrom(dateRange.value[0], false) : undefined,
        createdTo: dateRange.value ? isoFrom(dateRange.value[1], true) : undefined,
        orderBy: sortBy.value,
      },
      query,
    ),
  { failureMessage: "预警列表加载失败" },
);

function openAlert(alertId: number): void {
  void router.push({ name: "risk-alert-detail", params: { alertId } });
}

// 改筛选或改排序都是「换了一批数据」，回到第一页；停在第 3 页会看到空表，而那不是
// 新条件的结果，是页码的。
watch([levelFilter, statusFilter, dateRange, sortBy], reset);
onMounted(() => {
  void reset();
});

useTabSummary(
  (value) => emit("summary", value),
  () => ({
    headline: `等级 ${levelFilter.value || "全部"} · 状态 ${statusFilter.value || "全部"} · 时间 ${rangeLabel.value}`,
    // 写回的是过滤后的总数，不是本页条数：检查器说的是「筛完还剩几条」。
    count: total.value,
  }),
);
</script>

<template>
  <div class="alerts">
    <PanelCard title="筛选">
      <form class="filters" data-testid="alert-filters" @submit.prevent="reset">
        <label class="filters__field">
          <span class="filters__label">等级</span>
          <el-select v-model="levelFilter" name="alert-level" placeholder="全部" placement="top-start">
            <el-option label="全部" value="" />
            <el-option v-for="level in ALERT_LEVELS" :key="level" :label="level" :value="level" />
          </el-select>
        </label>

        <label class="filters__field">
          <span class="filters__label">状态</span>
          <el-select v-model="statusFilter" name="alert-status" placeholder="全部" placement="top-start">
            <el-option label="全部" value="" />
            <el-option v-for="status in ALERT_STATUSES" :key="status" :label="status" :value="status" />
          </el-select>
        </label>

        <label class="filters__field filters__field--wide">
          <span class="filters__label">产生时间</span>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
          />
        </label>

        <label class="filters__field">
          <span class="filters__label">排序</span>
          <el-select v-model="sortBy" name="alert-sort" placement="top-start">
            <el-option
              v-for="option in ALERT_SORT_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </label>

        <el-button name="apply-alert-filters" native-type="submit" :loading="loading">查询</el-button>
      </form>
    </PanelCard>

    <PanelCard title="预警列表">
      <p v-if="alertError" class="alerts__error" role="alert" data-testid="alert-error">
        {{ alertError }}
      </p>
      <p v-else-if="!loading && !items.length" class="alerts__empty" data-testid="alerts-empty">
        暂无预警
      </p>

      <!--
        列宽是「最小宽度」而不是固定宽度：el-table 只有在各列最小宽度之和大于容器时才出横向滚动条。
        时间格式统一成 `YYYY-MM-DD HH:mm:ss` 后，时间串从 138px 涨到 145px（含内边距 169px），
        原来的 160px 装不下，会被拆成两行；合计也顶出了容器。
        现在按「1200px 视口 + 侧栏展开 + 检查器收起」的可用宽度（873px）留余量，把九列压到合计 862px：
        时间列给足 172px 单行显示，余下列依表头文案 / tag / 按钮的固有宽度取下限。
        多余宽度仍由 el-table 按列分配；侧栏与检查器都展开、宽度真的不够时可横向滚动。
      -->
      <el-table v-if="items.length" :data="items" data-testid="alerts-table">
        <el-table-column label="产生时间" min-width="172">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="客户" prop="customer_name" min-width="72" />
        <el-table-column label="预警类型" prop="alert_type" min-width="84" />
        <el-table-column label="等级" min-width="78">
          <template #default="{ row }">
            <el-tag :type="levelTagType(row.alert_level)">{{ row.alert_level }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="置信度" min-width="68">
          <template #default="{ row }">{{ confidenceText(row.confidence) }}</template>
        </el-table-column>
        <el-table-column label="命中规则" min-width="138">
          <template #default="{ row }">
            {{ row.rule_count }} 条 · {{ row.rule_codes.join("、") }}
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="82">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="工单" min-width="82">
          <template #default="{ row }">
            <el-tag v-if="row.work_order_status" :type="workOrderTagType(row.work_order_status)">
              {{ row.work_order_status }}
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="86">
          <template #default="{ row }">
            <el-button size="small" name="open-alert" @click="openAlert(row.id)">查看</el-button>
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
.alerts {
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

.filters__field--wide {
  min-width: calc(var(--wm-space-6) * 9);
}

.filters__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.alerts__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.alerts__empty {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}
</style>
