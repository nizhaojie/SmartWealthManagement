<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { PageHeader, PanelCard } from "@wealth/shared";
import { listCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import { errorMessage, formatDateTime } from "../format";
import CustomerInspector from "../inspector/CustomerInspector.vue";
import { useInspector } from "../shell/pageSlots";
import { useCurrentCustomerStore } from "../stores/currentCustomer";
import { generatePlan, getMyHistory, getQueue } from "./api";
import { reviewSummaryLabel, reviewTarget } from "./reviewView";
import type { AdvisoryHistoryEntry, AdvisoryQueue, ContentType } from "./types";

// 生成侧重是顾问对这次生成的口径选择，不是客户属性。
const TILT_OPTIONS = ["均衡", "收益优先", "流动性优先"] as const;

const router = useRouter();
const currentCustomer = useCurrentCustomerStore();

const queue = ref<AdvisoryQueue>({ pending_requests: [], pending_reviews: [] });
const history = ref<AdvisoryHistoryEntry[]>([]);
const customers = ref<CustomerListItem[]>([]);
const loadError = ref("");

const directCustomerId = ref<number | null>(null);
const tilt = ref<string>(TILT_OPTIONS[0]);
const generateError = ref("");
const generating = ref(false);

// 待生成请求的生成弹窗：请求带着客户来，顾问只需要选口径。
const dialogOpen = ref(false);
const dialogRequestId = ref<number | null>(null);
const dialogCustomerId = ref<number | null>(null);

const pendingRequestCount = computed(() => queue.value.pending_requests.length);
const pendingReviewCount = computed(() => queue.value.pending_reviews.length);

async function loadAll(): Promise<void> {
  loadError.value = "";
  try {
    const [nextQueue, nextHistory, nextCustomers] = await Promise.all([
      getQueue(),
      getMyHistory(),
      listCustomers(),
    ]);
    queue.value = nextQueue;
    history.value = nextHistory;
    customers.value = nextCustomers;
  } catch (error) {
    loadError.value = errorMessage(error, "投顾队列加载失败");
  }
}

function formatWaiting(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时 ${minutes % 60} 分钟`;
  return `${Math.floor(hours / 24)} 天 ${hours % 24} 小时`;
}

function openGenerateDialog(requestId: number, customerId: number): void {
  dialogRequestId.value = requestId;
  dialogCustomerId.value = customerId;
  tilt.value = TILT_OPTIONS[0];
  generateError.value = "";
  dialogOpen.value = true;
}

async function confirmGenerate(): Promise<void> {
  if (dialogCustomerId.value === null) return;
  generating.value = true;
  generateError.value = "";
  try {
    const draft = await generatePlan({
      customerId: dialogCustomerId.value,
      tilt: tilt.value,
      advisoryRequestId: dialogRequestId.value,
    });
    currentCustomer.setCustomer(dialogCustomerId.value);
    dialogOpen.value = false;
    await router.push({ name: "advisory-review", params: { draftId: draft.id } });
  } catch (error) {
    generateError.value = errorMessage(error, "生成方案失败");
  } finally {
    generating.value = false;
  }
}

async function generateDirect(): Promise<void> {
  if (directCustomerId.value === null) return;
  generating.value = true;
  generateError.value = "";
  try {
    const draft = await generatePlan({
      customerId: directCustomerId.value,
      tilt: tilt.value,
      advisoryRequestId: null,
    });
    currentCustomer.setCustomer(directCustomerId.value);
    await router.push({ name: "advisory-review", params: { draftId: draft.id } });
  } catch (error) {
    generateError.value = errorMessage(error, "生成方案失败");
  } finally {
    generating.value = false;
  }
}

// 待审队列与历史记录用的是同一对标识（内容类型 + 内容引用），因此打开它们是同一件事：
// 两类内容各有自己的审核页，跳哪一张由类型决定（见 reviewView 的 reviewTarget）。
function openReview(row: { content_type: ContentType; content_ref: number }): void {
  void router.push(reviewTarget(row.content_type, row.content_ref));
}

useInspector(() => ({ component: CustomerInspector }));

onMounted(loadAll);
</script>

<template>
  <div class="advisory">
    <PageHeader title="投顾助手" :breadcrumb="['投顾助手']" />

    <p v-if="loadError" class="advisory__error" role="alert" data-testid="queue-error">
      {{ loadError }}
    </p>

    <PanelCard title="为客户发起生成">
      <div class="direct">
        <label class="direct__field">
          <span class="direct__label">客户</span>
          <el-select v-model="directCustomerId" name="direct-customer" placeholder="选择客户" data-testid="direct-customer-select">
            <el-option
              v-for="customer in customers"
              :key="customer.id"
              :label="customer.real_name"
              :value="customer.id"
            />
          </el-select>
        </label>
        <label class="direct__field">
          <span class="direct__label">生成侧重</span>
          <el-select v-model="tilt" name="direct-tilt" data-testid="direct-tilt-select">
            <el-option v-for="option in TILT_OPTIONS" :key="option" :label="option" :value="option" />
          </el-select>
        </label>
        <el-button
          type="primary"
          name="open-direct-generate"
          data-testid="open-direct-generate"
          :disabled="directCustomerId === null"
          :loading="generating"
          @click="generateDirect"
        >
          生成方案
        </el-button>
      </div>
      <p v-if="generateError" class="advisory__error" role="alert" data-testid="generate-error">
        {{ generateError }}
      </p>
    </PanelCard>

    <PanelCard :title="`待生成的方案请求（${pendingRequestCount}）`">
      <p v-if="!queue.pending_requests.length" class="advisory__empty">
        暂无待生成的方案请求
      </p>
      <el-table v-else :data="queue.pending_requests" data-testid="pending-requests-table">
        <el-table-column label="客户" prop="customer_name" sortable />
        <el-table-column label="请求编号" prop="request_no" width="160" />
        <el-table-column label="等待时长" width="160">
          <template #default="{ row }">{{ formatWaiting(row.waiting_seconds) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button
              size="small"
              name="open-generate"
              data-testid="open-generate"
              @click="openGenerateDialog(row.id, row.customer_id)"
            >
              生成方案
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </PanelCard>

    <PanelCard :title="`待审核（${pendingReviewCount}）`">
      <p v-if="!queue.pending_reviews.length" class="advisory__empty">暂无待审核内容</p>
      <el-table v-else :data="queue.pending_reviews" data-testid="pending-reviews-table">
        <el-table-column label="客户" prop="customer_name" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" data-testid="pending-review-type">{{ row.content_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" prop="status" width="110" />
        <el-table-column label="内容摘要" min-width="200">
          <template #default="{ row }">{{ reviewSummaryLabel(row) }}</template>
        </el-table-column>
        <el-table-column label="等待时长" width="160">
          <template #default="{ row }">{{ formatWaiting(row.waiting_seconds) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button
              size="small"
              name="open-review"
              data-testid="open-review"
              @click="openReview(row)"
            >
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </PanelCard>

    <PanelCard title="我审核过的记录">
      <p v-if="!history.length" class="advisory__empty">还没有审核过的记录</p>
      <el-table v-else :data="history" data-testid="history-table">
        <el-table-column label="客户" prop="customer_name" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" data-testid="history-type">{{ row.content_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" prop="action" width="100" />
        <el-table-column label="驳回理由" prop="reason" min-width="200">
          <template #default="{ row }">{{ row.reason ?? "—" }}</template>
        </el-table-column>
        <el-table-column label="操作时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.decided_at) }}</template>
        </el-table-column>
        <el-table-column label="查看" width="90">
          <template #default="{ row }">
            <el-button
              size="small"
              name="open-history-review"
              data-testid="open-history-review"
              @click="openReview(row)"
            >
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </PanelCard>

    <el-dialog v-model="dialogOpen" title="生成方案" width="380px">
      <label class="direct__field">
        <span class="direct__label">生成侧重</span>
        <el-select v-model="tilt" name="tilt" data-testid="tilt-select">
          <el-option v-for="option in TILT_OPTIONS" :key="option" :label="option" :value="option" />
        </el-select>
      </label>
      <p v-if="generateError" class="advisory__error" role="alert" data-testid="generate-error">
        {{ generateError }}
      </p>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button
          type="primary"
          data-testid="confirm-generate"
          :loading="generating"
          @click="confirmGenerate"
        >
          确认生成
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.advisory {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.direct {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--wm-space-3) var(--wm-space-4);
}

.direct__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: calc(var(--wm-space-6) * 5);
}

.direct__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.advisory__empty {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.advisory__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
