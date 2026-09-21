<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, PageHeader, PanelCard } from "@wealth/shared";
import { errorMessage, formatDateTime } from "../format";
import CustomerInspector from "../inspector/CustomerInspector.vue";
import { useInspector } from "../shell/pageSlots";
import { useAuthStore } from "../stores/auth";
import { useCurrentCustomerStore } from "../stores/currentCustomer";
import { workOrderTagType } from "../work-orders/workOrderView";
import { deriveWorkOrder, escalateAlert, excludeAlert, getAlert } from "./api";
import {
  alertSourceNote,
  alertSourceTagType,
  canDeriveWorkOrder,
  canDispose,
  confidenceText,
  levelTagType,
  statusTagType,
} from "./riskView";
import type { AlertDetail } from "./types";

/**
 * 预警详情：命中依据、客户、交易、历史，以及三个处置动作。
 * 三个动作共用同一份理由，且理由必填；非风控专员只看到一句说明。
 */
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const currentCustomer = useCurrentCustomerStore();

const alertId = computed(() => Number(route.params.alertId));

const detail = ref<AlertDetail | null>(null);
const loading = ref(true);
const forbidden = ref(false);
const forbiddenMessage = ref("");
const loadError = ref("");

const reason = ref("");
const actionError = ref("");
const submitting = ref(false);

const role = computed(() => auth.currentEmployee?.employee_role);
const status = computed(() => detail.value?.status ?? "未处理");
const disposable = computed(() => canDispose(role.value, status.value));
const derivable = computed(() =>
  detail.value
    ? canDeriveWorkOrder(role.value, {
        status: detail.value.status,
        work_order_id: detail.value.work_order?.id ?? null,
      })
    : false,
);
const reasonReady = computed(() => reason.value.trim() !== "");

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  forbidden.value = false;

  if (!Number.isFinite(alertId.value)) {
    loadError.value = "预警编号无效";
    loading.value = false;
    return;
  }

  try {
    detail.value = await getAlert(alertId.value);
    // 这条预警属于某位客户，检查器跟着显示他。
    currentCustomer.setCustomer(detail.value.customer_id);
  } catch (error) {
    if (error instanceof ApiError && error.code === 403) {
      forbidden.value = true;
      forbiddenMessage.value = error.message;
    } else {
      loadError.value = errorMessage(error, "预警详情加载失败");
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
    await load();
  } catch (error) {
    actionError.value = errorMessage(error, "处置失败");
  } finally {
    submitting.value = false;
  }
}

function exclude(): void {
  void run(() => excludeAlert(alertId.value, reason.value.trim()));
}

function escalate(): void {
  void run(() => escalateAlert(alertId.value, reason.value.trim()));
}

function derive(): void {
  void run(() => deriveWorkOrder(alertId.value, reason.value.trim()));
}

function openWorkOrder(workOrderId: number): void {
  void router.push({ name: "work-order-detail", params: { workOrderId } });
}

function backToAlerts(): void {
  void router.push("/risk-monitoring");
}

useInspector(() => ({ component: CustomerInspector }));

watch(alertId, load, { immediate: true });
</script>

<template>
  <div class="alert-detail">
    <PageHeader :title="detail ? `预警 #${detail.id} · ${detail.alert_type}` : '预警详情'" :breadcrumb="['风控监测', '预警详情']">
      <template #actions>
        <el-button size="small" name="back-to-alerts" data-testid="back-to-alerts" @click="backToAlerts">
          返回列表
        </el-button>
      </template>
    </PageHeader>

    <p v-if="forbidden" class="alert-detail__forbidden" role="alert" data-testid="alert-forbidden">
      {{ forbiddenMessage || "无权查看这条预警" }}
    </p>
    <p v-else-if="loadError" class="alert-detail__error" role="alert" data-testid="alert-load-error">
      {{ loadError }}
    </p>
    <p v-else-if="loading" class="alert-detail__hint">加载中…</p>

    <template v-else-if="detail">
      <div class="alert-detail__tags">
        <el-tag :type="levelTagType(detail.alert_level)" data-testid="alert-level">
          {{ detail.alert_level }}
        </el-tag>
        <el-tag :type="statusTagType(detail.status)" data-testid="alert-status">
          {{ detail.status }}
        </el-tag>
        <span class="alert-detail__confidence" data-testid="alert-confidence">
          置信度 {{ confidenceText(detail.confidence) }}（仅用于排序与分级展示）
        </span>
      </div>

      <p class="alert-detail__source" data-testid="alert-source">
        来源
        <el-tag :type="alertSourceTagType(detail.source)" size="small">
          {{ detail.source }}
        </el-tag>
        <span v-if="alertSourceNote(detail.source)" class="alert-detail__source-note">
          {{ alertSourceNote(detail.source) }}
        </span>
      </p>

      <p v-if="detail.handled_by_name" class="alert-detail__handler" data-testid="handled-by">
        处置人 {{ detail.handled_by_name }} · {{ detail.handle_result ?? "—" }}
      </p>

      <PanelCard title="命中依据">
        <el-table v-if="detail.rule_hits.length" :data="detail.rule_hits" data-testid="rule-hits-table">
          <el-table-column label="规则" min-width="180">
            <template #default="{ row }">{{ row.rule_name }}（{{ row.rule_code }}）</template>
          </el-table-column>
          <el-table-column label="判定字段" prop="field_label" width="130" />
          <el-table-column label="实测值" prop="observed_value" width="130" />
          <el-table-column label="阈值" width="130">
            <template #default="{ row }">{{ row.operator_symbol }} {{ row.threshold }}</template>
          </el-table-column>
          <el-table-column label="依据" prop="evidence" min-width="200" />
        </el-table>
        <p v-else class="alert-detail__trigger" data-testid="trigger-detail">
          {{ detail.trigger_detail || "这条预警没有结构化的命中依据。" }}
        </p>
      </PanelCard>

      <PanelCard title="客户">
        <el-descriptions :column="4" border data-testid="customer-card">
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
      </PanelCard>

      <PanelCard title="关联交易">
        <p v-if="!detail.transactions.length" class="alert-detail__hint">没有关联的交易记录。</p>
        <el-table v-else :data="detail.transactions" data-testid="transactions-table">
          <el-table-column label="流水号" prop="transaction_no" width="170" />
          <el-table-column label="类型" prop="transaction_type" width="100" />
          <el-table-column label="产品" prop="product_name" min-width="150" />
          <el-table-column label="金额" prop="amount" width="130" />
          <el-table-column label="状态" prop="status" width="100" />
          <el-table-column label="发生时间" width="180">
            <template #default="{ row }">{{ formatDateTime(row.occurred_at) }}</template>
          </el-table-column>
        </el-table>
      </PanelCard>

      <PanelCard title="该客户的历史预警">
        <p v-if="!detail.customer_history.length" class="alert-detail__hint" data-testid="history-empty">
          这位客户没有其他预警记录
        </p>
        <el-table v-else :data="detail.customer_history" data-testid="history-table">
          <el-table-column label="预警类型" prop="alert_type" min-width="150" />
          <el-table-column label="等级" width="90">
            <template #default="{ row }">
              <el-tag :type="levelTagType(row.alert_level)">{{ row.alert_level }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" prop="status" width="100" />
          <el-table-column label="命中规则" min-width="180">
            <template #default="{ row }">{{ row.rule_codes.join("、") }}</template>
          </el-table-column>
          <el-table-column label="产生时间" width="180">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </PanelCard>

      <PanelCard title="工单">
        <template v-if="detail.work_order">
          <p data-testid="work-order-link">
            已派生工单 {{ detail.work_order.work_order_no }}（{{ detail.work_order.status }}）
            <el-tag :type="workOrderTagType(detail.work_order.status)" size="small">
              {{ detail.work_order.status }}
            </el-tag>
          </p>
          <el-button size="small" name="open-work-order" @click="openWorkOrder(detail.work_order.id)">
            查看处置
          </el-button>
        </template>
        <p v-else class="alert-detail__hint">这条预警还没有派生工单。</p>
      </PanelCard>

      <PanelCard v-if="disposable" title="处置" data-testid="disposition">
        <el-input
          v-model="reason"
          name="disposition-reason"
          type="textarea"
          :rows="3"
          placeholder="处置理由（必填）"
          data-testid="disposition-reason"
        />
        <div class="disposition__actions">
          <el-button
            name="derive-work-order"
            data-testid="derive-work-order"
            :disabled="!reasonReady || !derivable"
            :loading="submitting"
            @click="derive"
          >
            派生工单
          </el-button>
          <el-button
            name="escalate-alert"
            data-testid="escalate-alert"
            :disabled="!reasonReady"
            :loading="submitting"
            @click="escalate"
          >
            升级
          </el-button>
          <el-button
            type="danger"
            name="exclude-alert"
            data-testid="exclude-alert"
            :disabled="!reasonReady"
            :loading="submitting"
            @click="exclude"
          >
            判定为误报（排除）
          </el-button>
        </div>
        <p v-if="actionError" class="alert-detail__error" role="alert" data-testid="action-error">
          {{ actionError }}
        </p>
      </PanelCard>

      <PanelCard v-else-if="detail.status === '未处理'" title="处置">
        <p class="alert-detail__hint" data-testid="read-only-hint">
          当前角色只能查看，处置由风控专员完成。
        </p>
      </PanelCard>
    </template>
  </div>
</template>

<style scoped>
.alert-detail {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.alert-detail__tags {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
}

.alert-detail__confidence,
.alert-detail__handler,
.alert-detail__source {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.alert-detail__source {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
}

.alert-detail__source-note {
  color: var(--wm-text-muted);
}

.alert-detail__hint,
.alert-detail__trigger {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.75;
  white-space: pre-wrap;
}

.alert-detail__error,
.alert-detail__forbidden {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.alert-detail__forbidden {
  padding: var(--wm-space-4);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-color-danger);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-card);
}

.disposition__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--wm-space-2);
  margin-top: var(--wm-space-3);
}
</style>
