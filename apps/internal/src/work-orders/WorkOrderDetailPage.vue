<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, PageHeader, PanelCard } from "@wealth/shared";
import { errorMessage, formatDateTime } from "../format";
import CustomerInspector from "../inspector/CustomerInspector.vue";
import { useInspector } from "../shell/pageSlots";
import { useAuthStore } from "../stores/auth";
import { useCurrentCustomerStore } from "../stores/currentCustomer";
import { acceptWorkOrder, closeWorkOrder, completeWorkOrder, getWorkOrder } from "./api";
import type { WorkOrderDetail } from "./types";
import { canHandleWorkOrder, transitionFromLabel, workOrderTagType } from "./workOrderView";

/**
 * 工单详情与流转：接单 / 办结（需结论）/ 关闭。
 * 每一次流转都必须写理由并留下处置人——终态没有下一步，界面据此换成一句说明。
 */
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const currentCustomer = useCurrentCustomerStore();

const workOrderId = computed(() => Number(route.params.workOrderId));

const detail = ref<WorkOrderDetail | null>(null);
const loading = ref(true);
const forbidden = ref(false);
const forbiddenMessage = ref("");
const loadError = ref("");

const reason = ref("");
const conclusion = ref("");
const actionError = ref("");
const submitting = ref(false);

const role = computed(() => auth.currentEmployee?.employee_role);
const status = computed(() => detail.value?.status ?? "待处理");
const canAct = computed(() => canHandleWorkOrder(role.value, status.value));
const isTerminal = computed(() => status.value === "已完成" || status.value === "已关闭");
const reasonReady = computed(() => reason.value.trim() !== "");
const conclusionReady = computed(() => conclusion.value.trim() !== "");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  forbidden.value = false;

  if (!Number.isFinite(workOrderId.value)) {
    loadError.value = "工单编号无效";
    loading.value = false;
    return;
  }

  try {
    detail.value = await getWorkOrder(workOrderId.value);
    if (detail.value.customer_id !== null) {
      currentCustomer.setCustomer(detail.value.customer_id);
    }
  } catch (error) {
    if (error instanceof ApiError && error.code === 403) {
      forbidden.value = true;
      forbiddenMessage.value = error.message;
    } else {
      loadError.value = errorMessage(error, "工单加载失败");
    }
  } finally {
    loading.value = false;
  }
}

async function run(action: () => Promise<unknown>): Promise<void> {
  actionError.value = "";
  submitting.value = true;
  try {
    await action();
    reason.value = "";
    conclusion.value = "";
    await load();
  } catch (error) {
    actionError.value = errorMessage(error, "流转失败");
  } finally {
    submitting.value = false;
  }
}

function accept(): void {
  void run(() => acceptWorkOrder(workOrderId.value, reason.value.trim()));
}

function complete(): void {
  void run(() =>
    completeWorkOrder(workOrderId.value, {
      reason: reason.value.trim(),
      conclusion: conclusion.value.trim(),
    }),
  );
}

function close(): void {
  void run(() =>
    closeWorkOrder(workOrderId.value, {
      reason: reason.value.trim(),
      conclusion: conclusion.value.trim(),
    }),
  );
}

function backToList(): void {
  void router.push("/work-orders");
}

useInspector(() => ({ component: CustomerInspector }));

watch(workOrderId, load, { immediate: true });
</script>

<template>
  <div class="work-order-detail">
    <PageHeader
      :title="detail?.work_order_no ?? '工单详情'"
      :breadcrumb="['工单管理', '工单详情']"
    >
      <template #actions>
        <el-button size="small" name="back-to-work-orders" data-testid="back-to-work-orders" @click="backToList">
          返回列表
        </el-button>
      </template>
    </PageHeader>

    <p v-if="forbidden" class="work-order-detail__forbidden" role="alert" data-testid="work-order-forbidden">
      {{ forbiddenMessage || "无权查看这张工单" }}
    </p>
    <p v-else-if="loadError" class="work-order-detail__error" role="alert" data-testid="work-order-load-error">
      {{ loadError }}
    </p>
    <p v-else-if="loading" class="work-order-detail__hint">加载中…</p>

    <template v-else-if="detail">
      <el-tag :type="workOrderTagType(detail.status)" data-testid="work-order-status">
        {{ detail.status }}
      </el-tag>

      <PanelCard title="工单概况">
        <el-descriptions :column="3" border>
          <el-descriptions-item label="来源">{{ detail.order_type }}</el-descriptions-item>
          <el-descriptions-item label="优先级">{{ detail.priority }}</el-descriptions-item>
          <el-descriptions-item label="受理人">
            {{ detail.handler_name || "—" }}
          </el-descriptions-item>
          <el-descriptions-item label="最近理由">
            {{ detail.handle_reason ?? "—" }}
          </el-descriptions-item>
          <el-descriptions-item label="处置结论">
            {{ detail.handle_result ?? "—" }}
          </el-descriptions-item>
          <el-descriptions-item label="来源预警">
            {{ detail.alert_id ?? "—" }}
          </el-descriptions-item>
        </el-descriptions>
      </PanelCard>

      <PanelCard v-if="canAct" title="处置" data-testid="work-order-actions">
        <el-input
          v-model="reason"
          name="transition-reason"
          type="textarea"
          :rows="2"
          placeholder="流转理由（必填）"
          data-testid="transition-reason"
        />
        <el-input
          v-if="detail.status === '处理中'"
          v-model="conclusion"
          name="transition-conclusion"
          type="textarea"
          :rows="2"
          placeholder="处置结论（办结时必填）"
          data-testid="transition-conclusion"
          class="work-order-detail__conclusion"
        />

        <div class="work-order-detail__actions">
          <el-button
            v-if="detail.status === '待处理'"
            name="accept"
            data-testid="accept"
            :disabled="!reasonReady"
            :loading="submitting"
            @click="accept"
          >
            接单
          </el-button>

          <template v-else>
            <el-button
              type="primary"
              name="complete"
              data-testid="complete"
              :disabled="!reasonReady || !conclusionReady"
              :loading="submitting"
              @click="complete"
            >
              办结
            </el-button>
            <el-button
              type="danger"
              name="close"
              data-testid="close"
              :disabled="!reasonReady"
              :loading="submitting"
              @click="close"
            >
              关闭
            </el-button>
          </template>
        </div>

        <p v-if="actionError" class="work-order-detail__error" role="alert" data-testid="action-error">
          {{ actionError }}
        </p>
      </PanelCard>

      <PanelCard v-else-if="isTerminal" title="处置">
        <p class="work-order-detail__hint" data-testid="terminal-hint">
          工单已{{ detail.status.slice(1) }}，不能再流转。
        </p>
      </PanelCard>

      <PanelCard v-else title="处置">
        <p class="work-order-detail__hint" data-testid="read-only-hint">
          当前角色只能查看，接单 / 办结 / 关闭由风控专员完成。
        </p>
      </PanelCard>

      <PanelCard title="流转留痕">
        <p v-if="!detail.transitions.length" class="work-order-detail__hint">还没有流转记录。</p>
        <el-table v-else :data="detail.transitions" data-testid="transitions-table">
          <el-table-column label="流转" min-width="160">
            <template #default="{ row }">
              {{ transitionFromLabel(row.from_status) }} → {{ row.to_status }}
            </template>
          </el-table-column>
          <el-table-column label="处置人" prop="handler_name" width="120" />
          <el-table-column label="理由" prop="reason" min-width="200" />
          <el-table-column label="时间" width="180">
            <template #default="{ row }">{{ formatDateTime(row.handled_at) }}</template>
          </el-table-column>
        </el-table>
      </PanelCard>
    </template>
  </div>
</template>

<style scoped>
.work-order-detail {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  align-items: flex-start;
}

.work-order-detail > * {
  width: 100%;
}

.work-order-detail__conclusion {
  margin-top: var(--wm-space-3);
}

.work-order-detail__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--wm-space-2);
  margin-top: var(--wm-space-3);
}

.work-order-detail__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.7;
}

.work-order-detail__error,
.work-order-detail__forbidden {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.work-order-detail__forbidden {
  margin-top: 0;
  padding: var(--wm-space-4);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-color-danger);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-card);
}
</style>
