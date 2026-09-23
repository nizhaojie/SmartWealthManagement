<script setup lang="ts">
// 投顾工作台：待生成的方案请求、待审内容、审核历史。
//
// 三段列表各接一个分页条（ADR-0024），三者的取数来源不同：
// - 待审内容在 store 里（它与壳的角标是同一次取数，见 queueStore）；
// - 待生成的方案请求走方案请求接口的「待处理」一页；
// - 审核历史是顾问自己的一页。
// 三者互不牵动：翻其中一页不会重取另外两段。
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { PageHeader, PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { listAllCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import { errorMessage, formatDateTime } from "../format";
import CustomerInspector from "../inspector/CustomerInspector.vue";
import { useInspector } from "../shell/pageSlots";
import { useCurrentCustomerStore } from "../stores/currentCustomer";
import { generatePlan, getMyHistory, listQueueRequests } from "./api";
import { useAdvisoryQueueStore } from "./queueStore";
import { reviewSummaryLabel, reviewTarget } from "./reviewView";
import type { AdvisoryHistoryEntry, ContentType, PendingRequest } from "./types";

// 生成侧重是顾问对这次生成的口径选择，不是客户属性。
const TILT_OPTIONS = ["均衡", "收益优先", "流动性优先"] as const;

const router = useRouter();
const currentCustomer = useCurrentCustomerStore();
// 待审内容（当前页 + 计数）来自 store：它与壳的角标是同一次取数，本页不自己拉一份。
const queue = useAdvisoryQueueStore();

const customers = ref<CustomerListItem[]>([]);
// 客户目录那一段的失败；三段列表各自留自己的原因（store / usePagination）。
const pageError = ref("");

const directCustomerId = ref<number | null>(null);
const tilt = ref<string>(TILT_OPTIONS[0]);
const generateError = ref("");
const generating = ref(false);

// 待生成请求的生成弹窗：请求带着客户来，顾问只需要选口径。
const dialogOpen = ref(false);
const dialogRequestId = ref<number | null>(null);
const dialogCustomerId = ref<number | null>(null);

// 取不到时给一句「这一段怎么了」：页面上三段列表共用一条失败横幅，只留下服务端
// 那句话，看不出是方案请求还是别的一段。
const REQUESTS_FAILURE_HINT = "暂时取不到";

// 待生成的方案请求：状态筛选（`待处理`）在服务端做，`total` 才是过滤后的总数。
const {
  items: requestItems,
  total: requestTotal,
  page: requestPage,
  pageSize: requestPageSize,
  loading: requestsLoading,
  errorMessage: requestsError,
  goTo: goToRequests,
  reset: resetRequests,
} = usePagination<PendingRequest>((query) => listQueueRequests(query), {
  failureMessage: REQUESTS_FAILURE_HINT,
});

/** 「拉取失败」与「一件都没有」要分得开：失败时那句「暂无」是一句没人能担保的断言。 */
const requestsFailure = computed(() =>
  requestsError.value ? `方案请求加载失败：${requestsError.value}` : "",
);

const {
  items: historyItems,
  total: historyTotal,
  page: historyPage,
  pageSize: historyPageSize,
  loading: historyLoading,
  errorMessage: historyError,
  goTo: goToHistory,
  reset: resetHistory,
} = usePagination<AdvisoryHistoryEntry>((query) => getMyHistory(query), {
  failureMessage: "审核历史加载失败",
});

/**
 * 卡片标题上的数字：在途与失败时留 `undefined`，标题因此不带数字。
 *
 * 写「（0）」与写「暂无」是同一句没人能担保的断言——那时我们并不知道有几件。
 */
const pendingRequestCount = computed(() =>
  requestsLoading.value || requestsError.value ? undefined : requestTotal.value,
);

/** 顶部横幅：三段取数任何一段失败都在这里说一次，卡片上不再各写一遍。 */
const loadError = computed(
  () => pageError.value || queue.error || requestsFailure.value || historyError.value,
);

/** 计数没取到时标题不带数字：这时写「（0）」是一句没人能担保的断言。 */
function countTitle(label: string, count: number | undefined): string {
  return count === undefined ? label : `${label}（${count}）`;
}

async function loadAll(): Promise<void> {
  pageError.value = "";
  try {
    const [nextCustomers] = await Promise.all([
      // 生成方案要选一位客户：这里要的是完整目录而不是某一页（ADR-0024）。
      listAllCustomers(),
      queue.refresh(),
      resetRequests(),
      resetHistory(),
    ]);
    customers.value = nextCustomers;
  } catch (error) {
    // 三段列表各自吞掉自己的失败（store 与 usePagination 都会留一句原因），
    // 这里接住的只有客户目录那一段。
    pageError.value = errorMessage(error, "投顾工作台加载失败");
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
    // 生成会立刻产生一条待审内容：刷新待审那一页，角标不必等下一次进壳。
    await queue.refresh();
    // 这条请求已经从「待处理」里走了，页面上的这一页也要跟着变。
    await resetRequests();
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
    await queue.refresh();
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

    <PanelCard :title="countTitle('待生成的方案请求', pendingRequestCount)">
      <!-- 没取到数时不写「暂无」：那与「（0）」是同一句没人能担保的断言。 -->
      <p v-if="requestsError" class="advisory__empty" data-testid="queue-unavailable">
        队列暂不可用
      </p>
      <!-- 「一份都没有」才说暂无：越界页 `items` 为空而 `total` 不为零，那时该留的是分页条。 -->
      <p v-else-if="!requestsLoading && requestTotal === 0" class="advisory__empty">
        暂无待生成的方案请求
      </p>
      <el-table v-if="requestItems.length" :data="requestItems" data-testid="pending-requests-table">
        <!-- 不挂 `sortable`：列头排序是**前端**对整表排序，分页后只排得动这一页，
             翻页即乱（ADR-0024）。队列的先后由服务端定：等得最久的在前。 -->
        <el-table-column label="客户" prop="customer_name" />
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

      <!-- 取不到时 `total` 归零，分页条与表格同进同退：没有记录时它不该出现。 -->
      <PaginationBar
        v-if="requestTotal > 0"
        :total="requestTotal"
        :page="requestPage"
        :page-size="requestPageSize"
        :disabled="requestsLoading"
        @update:page="goToRequests"
      />
    </PanelCard>

    <PanelCard :title="countTitle('待审核', queue.pendingReviewCount)">
      <p v-if="queue.failed" class="advisory__empty" data-testid="queue-unavailable">
        队列暂不可用
      </p>
      <!-- 「一份都没有」才说暂无：越界页 `items` 为空而 `total` 不为零，那时该留的是分页条。 -->
      <p v-else-if="!queue.loading && queue.pendingReviewCount === 0" class="advisory__empty">
        暂无待审核内容
      </p>
      <el-table
        v-if="queue.pendingReviews.length"
        :data="queue.pendingReviews"
        data-testid="pending-reviews-table"
      >
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

      <!-- 计数没取到时（在途 / 失败）不给分页条：`total` 还是 0，条子无从画起。 -->
      <PaginationBar
        v-if="queue.pendingReviewCount"
        :total="queue.pendingReviewCount"
        :page="queue.page"
        :page-size="queue.pageSize"
        :disabled="queue.loading"
        @update:page="queue.goTo"
      />
    </PanelCard>

    <PanelCard title="我审核过的记录">
      <p
        v-if="!historyLoading && historyTotal === 0"
        class="advisory__empty"
        data-testid="history-empty"
      >
        还没有审核过的记录
      </p>
      <el-table v-if="historyItems.length" :data="historyItems" data-testid="history-table">
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

      <PaginationBar
        v-if="historyTotal > 0"
        :total="historyTotal"
        :page="historyPage"
        :page-size="historyPageSize"
        :disabled="historyLoading"
        @update:page="goToHistory"
      />
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
