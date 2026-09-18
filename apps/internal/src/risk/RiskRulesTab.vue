<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { PanelCard } from "@wealth/shared";
import { ElMessage } from "element-plus";
import { errorMessage } from "../format";
import { useAuthStore } from "../stores/auth";
import { listRiskRules, setRiskRuleEnabled, setRiskRuleThreshold } from "./api";
import type { RiskRule } from "./types";
import { canManageRiskRules, type TabSummary } from "./riskView";
import { useTabSummary } from "./useTabSummary";

// 规则管理：启停与阈值调整都只放开给风控专员，其他角色看到的是只读表格。
const emit = defineEmits<{ summary: [value: TabSummary] }>();

const auth = useAuthStore();
const canManage = computed(() => canManageRiskRules(auth.currentEmployee?.employee_role));

const rules = ref<RiskRule[]>([]);
const loading = ref(true);
const ruleError = ref("");

const editing = ref<RiskRule | null>(null);
const dialogOpen = ref(false);
const thresholdDraft = ref<Record<string, string>>({});
const thresholdReason = ref("");
const thresholdError = ref("");
const saving = ref(false);

const enabledCount = computed(() => rules.value.filter((rule) => rule.enabled).length);

async function loadRules(): Promise<void> {
  loading.value = true;
  ruleError.value = "";
  try {
    rules.value = await listRiskRules();
  } catch (error) {
    rules.value = [];
    ruleError.value = errorMessage(error, "规则列表加载失败");
  } finally {
    loading.value = false;
  }
}

function replaceRule(next: RiskRule): void {
  rules.value = rules.value.map((rule) => (rule.id === next.id ? next : rule));
}

async function toggleRule(rule: RiskRule, value: string | number | boolean): Promise<void> {
  ruleError.value = "";
  try {
    replaceRule(await setRiskRuleEnabled(rule.id, Boolean(value)));
  } catch (error) {
    ruleError.value = errorMessage(error, "启停变更失败");
    // 变更失败时以服务端为准重新拉一次，别让开关停在一个假的档位上。
    await loadRules();
  }
}

function openThreshold(rule: RiskRule): void {
  editing.value = rule;
  thresholdDraft.value = { ...rule.threshold };
  thresholdReason.value = "";
  thresholdError.value = "";
  dialogOpen.value = true;
}

async function submitThreshold(): Promise<void> {
  const rule = editing.value;
  if (!rule) return;
  if (!thresholdReason.value.trim()) {
    thresholdError.value = "调整理由不能为空";
    return;
  }
  saving.value = true;
  thresholdError.value = "";
  try {
    replaceRule(await setRiskRuleThreshold(rule.id, { ...thresholdDraft.value }, thresholdReason.value.trim()));
    dialogOpen.value = false;
    ElMessage.success("阈值已更新");
  } catch (error) {
    thresholdError.value = errorMessage(error, "阈值更新失败");
  } finally {
    saving.value = false;
  }
}

onMounted(loadRules);

useTabSummary(
  (value) => emit("summary", value),
  () => ({
    headline: `共 ${rules.value.length} 条规则 · ${enabledCount.value} 条启用`,
    count: rules.value.length,
  }),
);
</script>

<template>
  <div class="rules">
    <PanelCard title="规则管理">
      <p v-if="ruleError" class="rules__error" role="alert" data-testid="rule-error">
        {{ ruleError }}
      </p>
      <p v-if="!loading && !rules.length && !ruleError" class="rules__empty">还没有风控规则。</p>
      <p v-else-if="!canManage" class="rules__hint" data-testid="rule-read-only">
        当前角色只能查看规则；启停与阈值调整由风控专员完成。
      </p>

      <el-table v-if="rules.length" :data="rules" data-testid="rules-table">
        <el-table-column label="编号" prop="rule_code" width="140" />
        <el-table-column label="规则" prop="rule_name" min-width="160" />
        <el-table-column label="判定字段" prop="field_label" width="130" />
        <el-table-column label="算子" prop="operator_label" width="110" />
        <el-table-column label="阈值" prop="threshold_text" min-width="140" />
        <el-table-column label="启停" width="100">
          <template #default="{ row }">
            <el-switch
              :model-value="row.enabled"
              :disabled="!canManage"
              data-testid="rule-enabled"
              @change="toggleRule(row, $event)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button
              size="small"
              name="edit-threshold"
              data-testid="edit-threshold"
              :disabled="!canManage"
              @click="openThreshold(row)"
            >
              调整阈值
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </PanelCard>

    <el-dialog v-model="dialogOpen" :title="editing ? `调整阈值：${editing.rule_name}` : '调整阈值'" width="440px">
      <label v-for="(_, key) in thresholdDraft" :key="key" class="threshold__field">
        <span class="threshold__label">{{ key }}</span>
        <el-input v-model="thresholdDraft[key]" :name="`threshold-${key}`" data-testid="threshold-input" />
      </label>

      <label class="threshold__field">
        <span class="threshold__label">调整理由（必填）</span>
        <el-input
          v-model="thresholdReason"
          name="threshold-reason"
          type="textarea"
          :rows="3"
          data-testid="threshold-reason"
        />
      </label>

      <p v-if="thresholdError" class="rules__error" role="alert" data-testid="threshold-error">
        {{ thresholdError }}
      </p>

      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button
          type="primary"
          data-testid="save-threshold"
          :loading="saving"
          @click="submitThreshold"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.rules {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.rules__error {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.rules__empty,
.rules__hint {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.7;
}

.threshold__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  margin-bottom: var(--wm-space-3);
}

.threshold__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}
</style>
