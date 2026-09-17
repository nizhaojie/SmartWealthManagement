<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError } from "@wealth/shared";
import { currentEmployee } from "../auth/store";
import { acceptWorkOrder, closeWorkOrder, completeWorkOrder, getWorkOrder } from "./api";
import { canHandleWorkOrder, errorMessage, formatDateTime, workOrderTagType } from "./riskView";
import type { WorkOrderDetail } from "./types";

const route = useRoute();
const router = useRouter();

const workOrderId = computed(() => Number(route.params.workOrderId));

const detail = ref<WorkOrderDetail | null>(null);
const loading = ref(true);
const forbidden = ref(false);
const forbiddenMessage = ref("");
const loadError = ref("");

// 每次流转都要理由：它是「谁在什么时候因为什么把它推到这一步」里唯一由人写下的
// 那一部分。办结还要求处置结论，关闭不要求——不是每张工单都以「办成了」结束。
const reason = ref("");
const conclusion = ref("");
const actionError = ref("");
const submitting = ref(false);

const status = computed(() => detail.value?.status ?? "");
const canAct = computed(
  () =>
    detail.value !== null &&
    canHandleWorkOrder(currentEmployee.value?.employee_role, detail.value.status),
);
const reasonReady = computed(() => reason.value.trim() !== "");
const conclusionReady = computed(() => conclusion.value.trim() !== "");

async function load() {
  loading.value = true;
  forbidden.value = false;
  loadError.value = "";
  try {
    detail.value = await getWorkOrder(workOrderId.value);
  } catch (error) {
    detail.value = null;
    if (error instanceof ApiError && error.code === 403) {
      forbidden.value = true;
      forbiddenMessage.value = error.message;
    } else {
      loadError.value = errorMessage(error, "加载工单失败");
    }
  } finally {
    loading.value = false;
  }
}

async function run(action: () => Promise<unknown>, fallback: string) {
  if (!reasonReady.value) return;
  actionError.value = "";
  submitting.value = true;
  try {
    await action();
    reason.value = "";
    conclusion.value = "";
    await load();
  } catch (error) {
    actionError.value = errorMessage(error, fallback);
  } finally {
    submitting.value = false;
  }
}

function submitAccept() {
  return run(() => acceptWorkOrder(workOrderId.value, reason.value.trim()), "接单失败");
}

function submitComplete() {
  if (!conclusionReady.value) return;
  return run(
    () =>
      completeWorkOrder(workOrderId.value, {
        reason: reason.value.trim(),
        conclusion: conclusion.value.trim(),
      }),
    "办结失败",
  );
}

function submitClose() {
  return run(
    () =>
      closeWorkOrder(workOrderId.value, {
        reason: reason.value.trim(),
        conclusion: conclusion.value.trim(),
      }),
    "关闭失败",
  );
}

function backToList() {
  router.push({ name: "risk-monitoring" });
}

onMounted(load);
</script>

<template>
  <div class="work-order-detail" data-test="work-order-detail">
    <p v-if="loading">加载中…</p>
    <el-card v-else-if="forbidden" data-test="work-order-forbidden">
      <h2 role="alert">无权查看</h2>
      <p>{{ forbiddenMessage }}</p>
    </el-card>
    <p v-else-if="loadError" role="alert" class="work-order-detail__error" data-test="load-error">
      {{ loadError }}
    </p>

    <template v-else-if="detail">
      <header class="work-order-detail__header">
        <el-button data-test="back-to-work-orders" @click="backToList">返回工单列表</el-button>
        <h2>{{ detail.work_order_no }}</h2>
        <el-tag :type="workOrderTagType(detail.status)" data-test="work-order-status">
          {{ detail.status }}
        </el-tag>
      </header>

      <el-card>
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
      </el-card>

      <el-card v-if="canAct" data-test="work-order-actions">
        <h3>处置</h3>
        <el-input
          v-model="reason"
          type="textarea"
          :rows="2"
          placeholder="流转理由（必填）"
          data-test="transition-reason"
        />
        <el-input
          v-model="conclusion"
          type="textarea"
          :rows="2"
          class="work-order-detail__conclusion"
          placeholder="处置结论（办结时必填）"
          data-test="transition-conclusion"
        />
        <div class="work-order-detail__buttons">
          <el-button
            v-if="status === '待处理'"
            type="primary"
            :disabled="!reasonReady"
            :loading="submitting"
            data-test="accept"
            @click="submitAccept"
          >
            接单
          </el-button>
          <template v-else>
            <el-button
              type="primary"
              :disabled="!reasonReady || !conclusionReady"
              :loading="submitting"
              data-test="complete"
              @click="submitComplete"
            >
              办结
            </el-button>
            <el-button
              type="danger"
              :disabled="!reasonReady"
              :loading="submitting"
              data-test="close"
              @click="submitClose"
            >
              关闭
            </el-button>
          </template>
        </div>
        <p
          v-if="actionError"
          role="alert"
          class="work-order-detail__error"
          data-test="action-error"
        >
          {{ actionError }}
        </p>
      </el-card>
      <p v-else-if="detail.status === '已完成' || detail.status === '已关闭'" class="work-order-detail__hint" data-test="terminal-hint">
        工单已{{ detail.status.slice(1) }}，不能再流转。
      </p>
      <p v-else class="work-order-detail__hint" data-test="read-only-hint">
        当前角色只能查看，流转由风控专员完成。
      </p>

      <el-card>
        <h3>流转留痕</h3>
        <el-table :data="detail.transitions" data-test="transitions-table">
          <el-table-column label="流转" min-width="180">
            <template #default="{ row }">
              {{ row.from_status ?? "建单" }} → {{ row.to_status }}
            </template>
          </el-table-column>
          <el-table-column prop="handler_name" label="处置人" width="120" />
          <el-table-column prop="reason" label="理由" min-width="240" />
          <el-table-column label="时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.handled_at) }}
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.work-order-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.work-order-detail__header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.work-order-detail__header h2 {
  margin: 0;
}

.work-order-detail__conclusion {
  margin-top: 12px;
}

.work-order-detail__buttons {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.work-order-detail__error {
  color: #b42318;
}

.work-order-detail__hint {
  color: #909399;
}
</style>
