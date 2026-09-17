<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, SectionCard } from "@wealth/shared";
import { currentEmployee } from "../auth/store";
import { deriveWorkOrder, escalateAlert, excludeAlert, getAlert } from "./api";
import {
  canDeriveWorkOrder,
  canDispose,
  confidenceText,
  errorMessage,
  formatDateTime,
  levelTagType,
  statusTagType,
} from "./riskView";
import type { AlertDetail } from "./types";

const route = useRoute();
const router = useRouter();

const alertId = computed(() => Number(route.params.alertId));

const detail = ref<AlertDetail | null>(null);
const loading = ref(true);
const forbidden = ref(false);
const forbiddenMessage = ref("");
const loadError = ref("");

// 一个理由服务三个动作：理由说的是「你依据什么做出这个处置」，排除、升级与派生工单
// 要的是同一件事。空理由一律提交不了，后端也会再挡一次。
const reason = ref("");
const actionError = ref("");
const submitting = ref(false);

const employeeRole = computed(() => currentEmployee.value?.employee_role);
const disposable = computed(
  () => detail.value !== null && canDispose(employeeRole.value, detail.value.status),
);
const derivable = computed(
  () =>
    detail.value !== null &&
    canDeriveWorkOrder(employeeRole.value, {
      status: detail.value.status,
      work_order_id: detail.value.work_order?.id ?? null,
    }),
);
const reasonReady = computed(() => reason.value.trim() !== "");

async function load() {
  loading.value = true;
  forbidden.value = false;
  loadError.value = "";
  try {
    detail.value = await getAlert(alertId.value);
  } catch (error) {
    detail.value = null;
    if (error instanceof ApiError && error.code === 403) {
      forbidden.value = true;
      // 403 有两种成因（角色不对 / 角色对但不是这位客户的归属人），后端的 message
      // 已经分得清楚，直接透传。
      forbiddenMessage.value = error.message;
    } else {
      loadError.value = errorMessage(error, "加载预警详情失败");
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
    await load();
  } catch (error) {
    actionError.value = errorMessage(error, fallback);
  } finally {
    submitting.value = false;
  }
}

function submitExclude() {
  return run(() => excludeAlert(alertId.value, reason.value.trim()), "排除失败");
}

function submitEscalate() {
  return run(() => escalateAlert(alertId.value, reason.value.trim()), "升级失败");
}

function submitDerive() {
  return run(() => deriveWorkOrder(alertId.value, reason.value.trim()), "派生工单失败");
}

function backToList() {
  router.push({ name: "risk-monitoring" });
}

function openWorkOrder(workOrderId: number) {
  router.push({
    name: "risk-work-order-detail",
    params: { workOrderId: String(workOrderId) },
  });
}

onMounted(load);
</script>

<template>
  <div class="alert-detail" data-test="alert-detail">
    <p v-if="loading">加载中…</p>
    <SectionCard v-else-if="forbidden" title="无权查看" data-test="alert-forbidden">
      <p role="alert">{{ forbiddenMessage }}</p>
    </SectionCard>
    <p v-else-if="loadError" role="alert" class="alert-detail__error" data-test="alert-load-error">
      {{ loadError }}
    </p>

    <template v-else-if="detail">
      <header class="alert-detail__header">
        <el-button data-test="back-to-alerts" @click="backToList">返回预警列表</el-button>
        <h2 class="alert-detail__title">预警 #{{ detail.id }} · {{ detail.alert_type }}</h2>
        <el-tag :type="levelTagType(detail.alert_level)" data-test="alert-level">
          {{ detail.alert_level }}
        </el-tag>
        <el-tag :type="statusTagType(detail.status)" data-test="alert-status">
          {{ detail.status }}
        </el-tag>
      </header>

      <SectionCard title="命中依据">
        <!-- 依据落到字段与值：哪个字段、什么值、超过什么阈值。这是判断误报的全部依据，
             所以它在这里是分列的，不是一句「命中某某规则」。 -->
        <el-table
          v-if="detail.rule_hits.length"
          :data="detail.rule_hits"
          data-test="rule-hits-table"
        >
          <el-table-column prop="rule_name" label="规则" min-width="200">
            <template #default="{ row }">
              {{ row.rule_name }}（{{ row.rule_code }}）
            </template>
          </el-table-column>
          <el-table-column prop="field_label" label="判定字段" min-width="180" />
          <el-table-column prop="observed_value" label="实测值" width="140" />
          <el-table-column label="阈值" width="180">
            <template #default="{ row }">
              {{ row.operator_symbol }} {{ row.threshold }}
            </template>
          </el-table-column>
          <el-table-column prop="evidence" label="依据" min-width="260" />
        </el-table>
        <pre v-else class="alert-detail__trigger" data-test="trigger-detail">{{ detail.trigger_detail }}</pre>
        <p class="alert-detail__meta" data-test="alert-confidence">
          置信度 {{ confidenceText(detail.confidence) }}（仅用于排序与分级展示）
        </p>
        <p v-if="detail.handled_by_name" class="alert-detail__meta" data-test="handled-by">
          处置人 {{ detail.handled_by_name }} · {{ detail.handle_result }}
        </p>
      </SectionCard>

      <SectionCard title="客户" data-test="customer-card">
        <el-descriptions :column="4" border>
          <el-descriptions-item label="姓名">{{ detail.customer.real_name }}</el-descriptions-item>
          <el-descriptions-item label="客户分层">
            {{ detail.customer.customer_level }}
          </el-descriptions-item>
          <el-descriptions-item label="风险承受等级">
            {{ detail.customer.risk_level ?? "未评测" }}
          </el-descriptions-item>
          <el-descriptions-item label="客户经理">
            {{ detail.customer.manager_name || "—" }}
          </el-descriptions-item>
        </el-descriptions>
      </SectionCard>

      <SectionCard title="关联交易">
        <el-table :data="detail.transactions" data-test="transactions-table">
          <el-table-column prop="transaction_no" label="流水号" min-width="200" />
          <el-table-column prop="transaction_type" label="类型" width="90" />
          <el-table-column prop="product_name" label="产品" min-width="160" />
          <el-table-column prop="amount" label="金额" width="140" />
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column label="发生时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.occurred_at) }}
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard title="该客户的历史预警">
        <el-empty
          v-if="!detail.customer_history.length"
          description="这位客户没有其他预警记录"
          data-test="history-empty"
        />
        <el-table v-else :data="detail.customer_history" data-test="history-table">
          <el-table-column prop="alert_type" label="预警类型" min-width="140" />
          <el-table-column label="等级" width="90">
            <template #default="{ row }">
              <el-tag :type="levelTagType(row.alert_level)">{{ row.alert_level }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="100" />
          <el-table-column prop="rule_codes" label="命中规则" min-width="160">
            <template #default="{ row }">{{ row.rule_codes.join("、") }}</template>
          </el-table-column>
          <el-table-column label="产生时间" width="180">
            <template #default="{ row }">
              {{ formatDateTime(row.created_at) }}
            </template>
          </el-table-column>
        </el-table>
      </SectionCard>

      <SectionCard title="工单">
        <div v-if="detail.work_order" data-test="work-order-link">
          <p>
            已派生工单 {{ detail.work_order.work_order_no }}（{{ detail.work_order.status }}）
          </p>
          <el-button type="primary" @click="openWorkOrder(detail.work_order.id)">
            查看处置
          </el-button>
        </div>
        <p v-else>这条预警还没有派生工单。</p>
      </SectionCard>

      <SectionCard v-if="disposable" title="处置" data-test="disposition">
        <el-input
          v-model="reason"
          type="textarea"
          :rows="2"
          placeholder="处置理由（必填）"
          data-test="disposition-reason"
        />
        <div class="alert-detail__actions">
          <el-button
            type="primary"
            :disabled="!reasonReady || !derivable"
            :loading="submitting"
            data-test="derive-work-order"
            @click="submitDerive"
          >
            派生工单
          </el-button>
          <el-button
            :disabled="!reasonReady"
            :loading="submitting"
            data-test="escalate-alert"
            @click="submitEscalate"
          >
            升级
          </el-button>
          <el-button
            type="danger"
            :disabled="!reasonReady"
            :loading="submitting"
            data-test="exclude-alert"
            @click="submitExclude"
          >
            判定为误报（排除）
          </el-button>
        </div>
        <p v-if="actionError" role="alert" class="alert-detail__error" data-test="action-error">
          {{ actionError }}
        </p>
      </SectionCard>
      <p
        v-else-if="detail.status === '未处理'"
        class="alert-detail__hint"
        data-test="read-only-hint"
      >
        当前角色只能查看，处置由风控专员完成。
      </p>
    </template>
  </div>
</template>

<style scoped>
.alert-detail {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.alert-detail__header {
  display: flex;
  align-items: center;
  gap: var(--wm-space-3);
}

.alert-detail__title {
  margin: 0;
  color: var(--wm-text-primary);
}

.alert-detail__meta {
  color: var(--wm-text-secondary);
  margin: var(--wm-space-2) 0 0;
}

.alert-detail__trigger {
  white-space: pre-wrap;
  margin: 0;
  color: var(--wm-text-primary);
}

.alert-detail__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--wm-space-2);
  margin-top: var(--wm-space-3);
}

.alert-detail__error {
  color: var(--wm-color-danger);
}

.alert-detail__hint {
  color: var(--wm-text-muted);
}
</style>
