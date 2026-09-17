<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ApiError } from "@wealth/shared";
import AnalyticsResultView from "../analytics/AnalyticsResultView.vue";
import type { AnalyticsQueryResponse } from "../analytics/types";
import { RISK_OFFICER } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import {
  askRiskQuestion,
  listAlerts,
  listRiskQueryExamples,
  listRiskRules,
  listWorkOrders,
  setRiskRuleEnabled,
} from "./api";
import {
  ALERT_SORT_OPTIONS,
  confidenceText,
  errorMessage,
  formatDateTime,
  levelTagType,
  sortAlerts,
  statusTagType,
  workOrderTagType,
  type AlertSort,
} from "./riskView";
import {
  ALERT_LEVELS,
  ALERT_STATUSES,
  WORK_ORDER_STATUSES,
  type AlertLevel,
  type AlertStatus,
  type AlertSummary,
  type RiskRule,
  type WorkOrder,
  type WorkOrderStatus,
} from "./types";

const router = useRouter();

// 风控专员在这里处置，其他角色只看得到自己范围内的那一部分——「看得见」不等于
// 「能处置」，写操作由后端再挡一次。
const isRiskOfficer = computed(() => currentEmployee.value?.employee_role === RISK_OFFICER);

const activeTab = ref("alerts");

const alerts = ref<AlertSummary[]>([]);
const alertError = ref("");
const loadingAlerts = ref(false);
const levelFilter = ref<AlertLevel | "">("");
const statusFilter = ref<AlertStatus | "">("");
const dateRange = ref<[Date, Date] | null>(null);
const sortBy = ref<AlertSort>("created_desc");

const workOrders = ref<WorkOrder[]>([]);
const workOrderError = ref("");
const workOrderStatusFilter = ref<WorkOrderStatus | "">("");

const rules = ref<RiskRule[]>([]);
const ruleError = ref("");

// 自然语言查询：风控专员问「今天有哪些高风险预警」，不必自己组合筛选条件。
// 问句由风控监测 Agent 转成对预警语义视图的查询；模型只把结果讲成人话，
// 等级与依据仍来自规则引擎的确定性求值。sessionId 圈定这一轮工作台的追问
// 上下文（上一轮问题进入本轮），重新打开页面即重新开始。
const querySessionId = crypto.randomUUID();
const queryQuestion = ref("");
const askingQuery = ref(false);
const queryResult = ref<AnalyticsQueryResponse | null>(null);
const queryFailure = ref("");
const queryExamples = ref<{ question: string }[]>([]);

const visibleAlerts = computed(() => sortAlerts(alerts.value, sortBy.value));

async function askQuery() {
  const text = queryQuestion.value.trim();
  if (!text || askingQuery.value) {
    return;
  }
  askingQuery.value = true;
  queryFailure.value = "";
  try {
    queryResult.value = await askRiskQuestion({
      question: text,
      sessionId: querySessionId,
    });
  } catch (error) {
    queryResult.value = null;
    queryFailure.value =
      error instanceof ApiError ? error.message : "查询失败，请稍后重试";
  } finally {
    askingQuery.value = false;
  }
}

function reuseQueryQuestion(text: string) {
  queryQuestion.value = text;
}

async function loadAlerts() {
  loadingAlerts.value = true;
  alertError.value = "";
  try {
    const range = dateRange.value;
    alerts.value = await listAlerts({
      alertLevel: levelFilter.value || undefined,
      status: statusFilter.value || undefined,
      createdFrom: range ? range[0].toISOString() : undefined,
      createdTo: range ? range[1].toISOString() : undefined,
    });
  } catch (error) {
    alerts.value = [];
    alertError.value = errorMessage(error, "加载预警列表失败");
  } finally {
    loadingAlerts.value = false;
  }
}

async function loadWorkOrders() {
  workOrderError.value = "";
  try {
    workOrders.value = await listWorkOrders({
      status: workOrderStatusFilter.value || undefined,
    });
  } catch (error) {
    workOrders.value = [];
    workOrderError.value = errorMessage(error, "加载工单列表失败");
  }
}

async function loadRules() {
  ruleError.value = "";
  try {
    rules.value = await listRiskRules();
  } catch (error) {
    rules.value = [];
    ruleError.value = errorMessage(error, "加载规则列表失败");
  }
}

async function loadQueryExamples() {
  try {
    queryExamples.value = await listRiskQueryExamples();
  } catch {
    // 示例加载失败不阻塞提问主流程。
    queryExamples.value = [];
  }
}

async function toggleRule(rule: RiskRule, enabled: boolean) {
  ruleError.value = "";
  try {
    const updated = await setRiskRuleEnabled(rule.id, enabled);
    rules.value = rules.value.map((item) => (item.id === updated.id ? updated : item));
  } catch (error) {
    ruleError.value = errorMessage(error, "切换规则启停失败");
    await loadRules();
  }
}

function onRuleToggle(rule: RiskRule, value: unknown) {
  void toggleRule(rule, Boolean(value));
}

function openAlert(alertId: number) {
  router.push({ name: "risk-alert-detail", params: { alertId: String(alertId) } });
}

function openWorkOrder(workOrderId: number) {
  router.push({
    name: "risk-work-order-detail",
    params: { workOrderId: String(workOrderId) },
  });
}

watch([levelFilter, statusFilter, dateRange], loadAlerts);
watch(workOrderStatusFilter, loadWorkOrders);

onMounted(() => {
  void loadAlerts();
  void loadWorkOrders();
  void loadRules();
  void loadQueryExamples();
});
</script>

<template>
  <div class="risk-monitoring">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="预警列表" name="alerts">
        <div class="risk-monitoring__filters" data-test="alert-filters">
          <el-select
            v-model="levelFilter"
            placeholder="按等级筛选"
            clearable
            data-test="alert-level-filter"
            style="width: 160px"
          >
            <el-option v-for="level in ALERT_LEVELS" :key="level" :label="level" :value="level" />
          </el-select>
          <el-select
            v-model="statusFilter"
            placeholder="按状态筛选"
            clearable
            data-test="alert-status-filter"
            style="width: 160px"
          >
            <el-option
              v-for="status in ALERT_STATUSES"
              :key="status"
              :label="status"
              :value="status"
            />
          </el-select>
          <span data-test="alert-date-range">
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              style="width: 260px"
            />
          </span>
          <el-select v-model="sortBy" data-test="alert-sort" style="width: 220px">
            <el-option
              v-for="option in ALERT_SORT_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </div>

        <p v-if="alertError" role="alert" class="risk-monitoring__error" data-test="alert-error">
          {{ alertError }}
        </p>

        <el-empty
          v-if="!loadingAlerts && !alerts.length"
          description="暂无预警"
          data-test="alerts-empty"
        />
        <el-table v-else :data="visibleAlerts" data-test="alerts-table">
          <el-table-column label="产生时间" width="180">
            <template #default="{ row }: { row: AlertSummary }">
              {{ formatDateTime(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="customer_name" label="客户" width="110" />
          <el-table-column prop="alert_type" label="预警类型" width="120" />
          <el-table-column label="等级" width="90">
            <template #default="{ row }: { row: AlertSummary }">
              <el-tag :type="levelTagType(row.alert_level)" data-test="alert-level">
                {{ row.alert_level }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="100">
            <template #default="{ row }: { row: AlertSummary }">
              <span data-test="alert-confidence">{{ confidenceText(row.confidence) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="命中规则" min-width="160">
            <template #default="{ row }: { row: AlertSummary }">
              {{ row.rule_count }} 条 · {{ row.rule_codes.join("、") }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }: { row: AlertSummary }">
              <el-tag :type="statusTagType(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="工单" width="110">
            <template #default="{ row }: { row: AlertSummary }">
              <el-tag v-if="row.work_order_status" :type="workOrderTagType(row.work_order_status)">
                {{ row.work_order_status }}
              </el-tag>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }: { row: AlertSummary }">
              <el-button
                link
                type="primary"
                data-test="open-alert"
                @click="openAlert(row.id)"
              >
                查看
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="工单列表" name="work-orders">
        <div class="risk-monitoring__filters" data-test="work-order-filters">
          <el-select
            v-model="workOrderStatusFilter"
            placeholder="按状态筛选"
            clearable
            data-test="work-order-status-filter"
            style="width: 160px"
          >
            <el-option
              v-for="status in WORK_ORDER_STATUSES"
              :key="status"
              :label="status"
              :value="status"
            />
          </el-select>
        </div>

        <p
          v-if="workOrderError"
          role="alert"
          class="risk-monitoring__error"
          data-test="work-order-error"
        >
          {{ workOrderError }}
        </p>

        <el-empty
          v-if="!workOrders.length"
          description="暂无工单"
          data-test="work-orders-empty"
        />
        <el-table v-else :data="workOrders" data-test="work-orders-table">
          <el-table-column prop="work_order_no" label="工单编号" width="200" />
          <el-table-column label="来源" width="110">
            <template #default="{ row }: { row: WorkOrder }">
              {{ row.order_type }}
            </template>
          </el-table-column>
          <el-table-column prop="priority" label="优先级" width="90" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }: { row: WorkOrder }">
              <el-tag :type="workOrderTagType(row.status)" data-test="work-order-status">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="handler_name" label="受理人" width="110" />
          <el-table-column label="最近理由" min-width="200">
            <template #default="{ row }: { row: WorkOrder }">
              {{ row.handle_reason ?? "—" }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }: { row: WorkOrder }">
              <el-button
                link
                type="primary"
                data-test="open-work-order"
                @click="openWorkOrder(row.id)"
              >
                处置
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="规则管理" name="rules">
        <p v-if="ruleError" role="alert" class="risk-monitoring__error" data-test="rule-error">
          {{ ruleError }}
        </p>

        <el-table :data="rules" data-test="rules-table">
          <el-table-column prop="rule_code" label="编号" width="80" />
          <el-table-column prop="rule_name" label="规则" min-width="200" />
          <el-table-column prop="field_label" label="判定字段" width="200" />
          <el-table-column prop="operator_label" label="算子" width="120" />
          <el-table-column prop="threshold_text" label="阈值" width="120" />
          <el-table-column label="启停" width="90">
            <template #default="{ row }: { row: RiskRule }">
              <el-switch
                :model-value="row.enabled"
                :disabled="!isRiskOfficer"
                data-test="rule-enabled"
                @change="onRuleToggle(row, $event)"
              />
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="自然语言查询" name="query">
        <el-card>
          <div class="risk-monitoring__query-composer">
            <el-input
              v-model="queryQuestion"
              type="textarea"
              :rows="2"
              name="risk-question"
              placeholder="用日常语言提问，例如：今天有哪些高风险预警"
              @keydown.ctrl.enter="askQuery"
            />
            <el-button
              type="primary"
              :loading="askingQuery"
              data-test="ask-risk-query"
              @click="askQuery"
            >
              {{ askingQuery ? "正在查询…" : "提问" }}
            </el-button>
          </div>
          <div v-if="queryExamples.length" class="risk-monitoring__examples">
            <span class="risk-monitoring__hint">试试这样问：</span>
            <button
              v-for="example in queryExamples"
              :key="example.question"
              type="button"
              class="risk-monitoring__example"
              data-test="risk-query-example"
              @click="reuseQueryQuestion(example.question)"
            >
              {{ example.question }}
            </button>
          </div>
        </el-card>

        <el-alert
          v-if="queryFailure"
          type="info"
          :closable="false"
          data-test="risk-query-failure"
          :title="queryFailure"
        />

        <AnalyticsResultView v-if="queryResult" :result="queryResult" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.risk-monitoring {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.risk-monitoring__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
}

.risk-monitoring__error {
  color: #b42318;
}

.risk-monitoring__query-composer {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.risk-monitoring__examples {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.risk-monitoring__example {
  cursor: pointer;
  border: 1px solid #d3dce6;
  border-radius: 12px;
  background: #f4f4f5;
  padding: 2px 10px;
  font-size: 12px;
  color: #606266;
}

.risk-monitoring__example:hover {
  background: #e9e9eb;
}

.risk-monitoring__hint {
  color: #909399;
  font-size: 12px;
}
</style>
