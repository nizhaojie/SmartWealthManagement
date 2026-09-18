<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError, PanelCard } from "@wealth/shared";
import { generatePlan, getMyHistory, getQueue, listCustomersForPlan } from "./api";
import type { AdvisoryHistoryEntry, AdvisoryQueue, CustomerOption } from "./types";

const TILT_OPTIONS = [
  { value: "均衡", label: "均衡" },
  { value: "收益优先", label: "收益优先" },
  { value: "流动性优先", label: "流动性优先" },
];

const router = useRouter();

const queue = ref<AdvisoryQueue>({ pending_requests: [], pending_reviews: [] });
const history = ref<AdvisoryHistoryEntry[]>([]);
const customers = ref<CustomerOption[]>([]);
const loadError = ref("");

// 生成对话框服务两个入口：从待生成请求发起（带 requestId）与顾问自己
// 挑一位客户主动发起（requestId 为 null）——两者最终都是同一个生成调用。
const generating = ref<{ requestId: number | null; customerId: number } | null>(null);
const directGenerateCustomerId = ref<number | null>(null);
const generateError = ref("");
const tilt = ref(TILT_OPTIONS[0].value);

async function load() {
  loadError.value = "";
  try {
    [queue.value, history.value, customers.value] = await Promise.all([
      getQueue(),
      getMyHistory(),
      listCustomersForPlan(),
    ]);
  } catch (error) {
    loadError.value = error instanceof ApiError ? error.message : "加载队列失败";
  }
}

function openGenerateDialog(requestId: number | null, customerId: number) {
  generating.value = { requestId, customerId };
  generateError.value = "";
  tilt.value = TILT_OPTIONS[0].value;
}

function openDirectGenerateDialog() {
  if (directGenerateCustomerId.value === null) return;
  openGenerateDialog(null, directGenerateCustomerId.value);
}

async function confirmGenerate() {
  if (generating.value === null) return;
  generateError.value = "";
  try {
    const draft = await generatePlan({
      customerId: generating.value.customerId,
      tilt: tilt.value,
      advisoryRequestId: generating.value.requestId,
    });
    generating.value = null;
    await router.push({ name: "advisory-review", params: { draftId: draft.id } });
  } catch (error) {
    generateError.value = error instanceof ApiError ? error.message : "生成方案失败";
  }
}

function openReview(draftId: number) {
  router.push({ name: "advisory-review", params: { draftId } });
}

function formatWaiting(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时 ${minutes % 60} 分钟`;
  const days = Math.floor(hours / 24);
  return `${days} 天 ${hours % 24} 小时`;
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

onMounted(load);
</script>

<template>
  <div class="advisory-workspace">
    <p v-if="loadError" class="advisory-workspace__error" data-test="load-error">
      {{ loadError }}
    </p>

    <PanelCard title="为客户发起生成">
      <div class="advisory-workspace__direct-generate">
        <el-select v-model="directGenerateCustomerId" placeholder="选择客户" data-test="direct-customer-select">
          <el-option v-for="customer in customers" :key="customer.id" :label="customer.real_name" :value="customer.id" />
        </el-select>
        <el-button
          type="primary"
          data-test="open-direct-generate"
          :disabled="directGenerateCustomerId === null"
          @click="openDirectGenerateDialog"
        >
          生成方案
        </el-button>
      </div>
    </PanelCard>

    <PanelCard title="待生成的方案请求">
      <el-table :data="queue.pending_requests" data-test="pending-requests-table">
        <el-table-column prop="customer_name" label="客户" sortable />
        <el-table-column prop="request_no" label="请求编号" />
        <el-table-column
          label="等待时长"
          sortable
          :sort-by="(row: (typeof queue.pending_requests)[number]) => row.waiting_seconds"
        >
          <template #default="{ row }">{{ formatWaiting(row.waiting_seconds) }}</template>
        </el-table-column>
        <el-table-column label="操作">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              data-test="open-generate"
              @click="openGenerateDialog(row.id, row.customer_id)"
            >
              生成方案
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="!queue.pending_requests.length" class="advisory-workspace__hint">暂无待生成的方案请求</p>
    </PanelCard>

    <PanelCard title="待审核">
      <el-table :data="queue.pending_reviews" data-test="pending-reviews-table">
        <el-table-column prop="customer_name" label="客户" sortable />
        <el-table-column prop="status" label="状态" sortable />
        <el-table-column prop="tilt" label="生成侧重" />
        <el-table-column
          label="等待时长"
          sortable
          :sort-by="(row: (typeof queue.pending_reviews)[number]) => row.waiting_seconds"
        >
          <template #default="{ row }">{{ formatWaiting(row.waiting_seconds) }}</template>
        </el-table-column>
        <el-table-column label="操作">
          <template #default="{ row }">
            <el-button size="small" data-test="open-review" @click="openReview(row.draft_id)">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p v-if="!queue.pending_reviews.length" class="advisory-workspace__hint">暂无待审核内容</p>
    </PanelCard>

    <PanelCard title="我审核过的记录">
      <el-table :data="history" data-test="history-table">
        <el-table-column prop="customer_name" label="客户" />
        <el-table-column prop="action" label="操作" />
        <el-table-column prop="reason" label="驳回理由" />
        <el-table-column label="操作时间">
          <template #default="{ row }">{{ formatDateTime(row.decided_at) }}</template>
        </el-table-column>
      </el-table>
      <p v-if="!history.length" class="advisory-workspace__hint">还没有审核过的记录</p>
    </PanelCard>

    <el-dialog
      :model-value="generating !== null"
      title="生成方案"
      data-test="generate-dialog"
      @close="generating = null"
    >
      <el-form label-width="80px">
        <el-form-item label="生成侧重">
          <el-select v-model="tilt" data-test="tilt-select">
            <el-option v-for="option in TILT_OPTIONS" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <p v-if="generateError" class="advisory-workspace__error" data-test="generate-error">
        {{ generateError }}
      </p>
      <template #footer>
        <el-button @click="generating = null">取消</el-button>
        <el-button type="primary" data-test="confirm-generate" @click="confirmGenerate">
          确认生成
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.advisory-workspace {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.advisory-workspace__direct-generate {
  display: flex;
  gap: var(--wm-space-3);
  align-items: center;
}

.advisory-workspace__hint {
  color: var(--wm-text-muted);
  font-size: 12px;
  margin-bottom: 0;
}

.advisory-workspace__error {
  color: var(--wm-color-danger);
}
</style>
