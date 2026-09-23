<script setup lang="ts">
// 规则管理：启停与阈值调整都只放开给风控专员，其他角色看到的是只读表格。
//
// 列表分页由 `usePagination` 接管（ADR-0024）。规则按编号升序，是唯一一个排序键
// 本来就稳定（编号唯一）的列表，所以这里没有排序控件。
import { computed, onMounted, ref } from "vue";
import { PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { ElMessage } from "element-plus";
import { errorMessage } from "../format";
import { useAuthStore } from "../stores/auth";
import { listRiskRules, setRiskRuleEnabled, setRiskRuleThreshold } from "./api";
import type { RiskRule } from "./types";
import { canManageRiskRules, type TabSummary } from "./riskView";
import { useTabSummary } from "./useTabSummary";

const emit = defineEmits<{ summary: [value: TabSummary] }>();

const auth = useAuthStore();
const canManage = computed(() => canManageRiskRules(auth.currentEmployee?.employee_role));

const editing = ref<RiskRule | null>(null);
const dialogOpen = ref(false);
const thresholdDraft = ref<Record<string, string>>({});
const thresholdReason = ref("");
const thresholdError = ref("");
const saving = ref(false);

// 写操作的失败原因自己留一份，不复用列表的 `errorMessage`：`refresh()` 每次取数都会
// 把那个清空，于是「启停变更失败」会在随后那次成功重取的瞬间消失，只剩一个退回去的
// 开关，看起来像什么都没发生。
const actionError = ref("");

const {
  items: rules,
  total,
  page,
  pageSize,
  loading,
  errorMessage: ruleError,
  refresh,
  goTo,
  reset,
} = usePagination<RiskRule>((query) => listRiskRules(query), {
  failureMessage: "规则列表加载失败",
});

const enabledCount = computed(() => rules.value.filter((rule) => rule.enabled).length);

function replaceRule(next: RiskRule): void {
  rules.value = rules.value.map((rule) => (rule.id === next.id ? next : rule));
}

async function toggleRule(rule: RiskRule, value: string | number | boolean): Promise<void> {
  actionError.value = "";
  try {
    replaceRule(await setRiskRuleEnabled(rule.id, Boolean(value)));
  } catch (error) {
    actionError.value = errorMessage(error, "启停变更失败");
    // 变更失败时以服务端为准重取当前这一页，别让开关停在一个假的档位上。
    await refresh();
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

onMounted(() => {
  void reset();
});

useTabSummary(
  (value) => emit("summary", value),
  () => ({
    // 「共 N 条」是过滤后的总数，不是本页条数；启用条数只数得到本页，因此说清是「本页」，
    // 否则分页一开，这个数字会随翻页变。
    headline: `共 ${total.value} 条规则 · 本页 ${enabledCount.value} 条启用`,
    count: total.value,
  }),
);
</script>

<template>
  <div class="rules">
    <PanelCard title="规则管理">
      <p
        v-if="ruleError || actionError"
        class="rules__error"
        role="alert"
        data-testid="rule-error"
      >
        {{ ruleError || actionError }}
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

      <!-- 取不到时 `total` 归零，分页条与表格同进同退：没有规则时它不该出现。 -->
      <PaginationBar
        v-if="total > 0"
        :total="total"
        :page="page"
        :page-size="pageSize"
        :disabled="loading"
        @update:page="goTo"
      />
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
