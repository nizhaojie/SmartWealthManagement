<script setup lang="ts">
// 规则管理：查看、新建、编辑、删除、启停与调阈值都只放开给风控专员，其他角色看到的是只读表格。
// 调阈值没有独立入口——点「编辑」即可调整，保存时阈值变化单独走调阈值接口留痕。
//
// 列表分页由 `usePagination` 接管（ADR-0024）。规则按编号升序，是唯一一个排序键
// 本来就稳定（编号唯一）的列表，所以这里没有排序控件。
//
// 写入侧的界线（ADR-0026）：可改的是**组合**（在给定的字段、算子与值域里挑），不可改的是
// **表达**。因此表单里的可选项与允许搭配全部来自 `GET /schema`，组件里不留第二份清单；
// 判定形状（字段 / 算子 / 时间窗）连编辑都不给——要换判定方式只能删除后重建。
import { computed, onMounted, reactive, ref, watch } from "vue";
import { PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { ElMessage, ElMessageBox } from "element-plus";
import { errorMessage, formatDateTime, formatValue } from "../format";
import { useAuthStore } from "../stores/auth";
import {
  createRiskRule,
  deleteRiskRule,
  getRiskRuleSchema,
  listRiskRuleChanges,
  listRiskRules,
  setRiskRuleEnabled,
  setRiskRuleThreshold,
  updateRiskRule,
} from "./api";
import { ALERT_LEVELS, type AlertLevel, type RiskRule, type RiskRuleChange, type RiskRuleSchema } from "./types";
import {
  fieldSpec,
  operatorChoices,
  thresholdKeyLabel,
  thresholdKeys,
  thresholdPayload,
  usesWindowHours,
  valueRangeHint,
} from "./ruleEditor";
import { canManageRiskRules, type TabSummary } from "./riskView";
import { useTabSummary } from "./useTabSummary";

const emit = defineEmits<{ summary: [value: TabSummary] }>();

const auth = useAuthStore();
const canManage = computed(() => canManageRiskRules(auth.currentEmployee?.employee_role));

// 「显示已删除」默认关：默认视图就是「现在还算数的规则」。它是**服务端**参数
// （`include_deleted`）——前端过滤会让「共 N 条」与实际行数对不上（ADR-0024）。
const includeDeleted = ref(false);

const schema = ref<RiskRuleSchema | null>(null);
const schemaError = ref("");

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
} = usePagination<RiskRule>((query) => listRiskRules(query, includeDeleted.value), {
  failureMessage: "规则列表加载失败",
});

// 已删除的规则不参与匹配，它的 `enabled` 只是一个留在库里的旧值：数「本页几条启用」
// 时不算它，否则「显示已删除」一开，这个数字会虚高。
const enabledCount = computed(
  () => rules.value.filter((rule) => rule.enabled && !rule.deleted_at).length,
);

function isDeleted(rule: RiskRule): boolean {
  // 取不到这个字段就当作没删：判成「已删」会让一行规则无声地失去全部写入口。
  return Boolean(rule.deleted_at);
}

function replaceRule(next: RiskRule): void {
  rules.value = rules.value.map((rule) => (rule.id === next.id ? next : rule));
}

watch(includeDeleted, () => {
  // 筛选条件变了就回第一页：停在第 3 页会看到「筛选后为空」，那不是筛选的结果。
  void reset();
});

// ---------------- 理由：三个写入口共用的一个范式 ----------------

/**
 * 收一条必填理由，取消返回 null。
 *
 * `inputValidator` 是这里的关键：返回一句话就让弹框**不关**、把话显示在输入框下面。
 * 先关再校验会让「理由为空」变成一次消失的对话框，人只知道自己点了删除。
 * 理由放在提示框里而不是自建表单，是因为它只有一段自由文本、没有别的字段（Q16）。
 */
async function askReason(title: string, message: string, placeholder: string): Promise<string | null> {
  try {
    const result = await ElMessageBox.prompt(message, title, {
      confirmButtonText: "提交",
      cancelButtonText: "取消",
      inputPlaceholder: placeholder,
      inputValidator: (value: string) => (value.trim() ? true : "理由不能为空"),
    });
    const reason = String(result.value).trim();
    // 校验器已经挡住了空理由，这里再挡一次是为了不把「一条空理由能不能提交」交给浮层组件
    // 去保证：它一旦放行，写接口收到的是空字符串，而五个入口都要求理由非空。
    return reason === "" ? null : reason;
  } catch {
    // 取消不是失败：什么都不做，也不留错误文案。
    return null;
  }
}

async function toggleRule(rule: RiskRule): Promise<boolean> {
  const next = !rule.enabled;
  const reason = await askReason(
    `${next ? "启用" : "停用"}规则 ${rule.rule_code}`,
    `确定${next ? "启用" : "停用"}「${rule.rule_name}」？`,
    "写清这次启停的理由",
  );
  if (reason === null) return false;

  actionError.value = "";
  try {
    replaceRule(await setRiskRuleEnabled(rule.id, next, reason));
    return true;
  } catch (error) {
    actionError.value = errorMessage(error, "启停变更失败");
    // 返回 false 让开关弹回原档位（`before-change` 的语义），行上的状态一个字都不用改。
    // 重取当前这一页是另一件事：写操作被拒可能就是因为这一页旧了（比如这条规则已被别人
    // 删掉，已删除的规则不再接受写操作），不重取的话那一行会一直挂着一个改不动的开关。
    await refresh();
    return false;
  }
}

async function removeRule(rule: RiskRule): Promise<void> {
  const reason = await askReason(
    `删除规则 ${rule.rule_code}`,
    `删除「${rule.rule_name}」？删除是终态，没有恢复入口（要让它不生效请用启停）。`,
    "写清删除的理由",
  );
  if (reason === null) return;

  actionError.value = "";
  try {
    await deleteRiskRule(rule.id, reason);
    ElMessage.success("规则已删除");
    // 重取当前这一页，不回到第一页：删掉的未必是这一页唯一一条。
    await refresh();
  } catch (error) {
    actionError.value = errorMessage(error, "删除失败");
  }
}

// ---------------- 变更记录 ----------------

const changesOpen = ref(false);
const changesRule = ref<RiskRule | null>(null);
const changes = ref<RiskRuleChange[]>([]);
const changesLoading = ref(false);
const changesError = ref("");

/**
 * 变更记录：这个接口此前没有前端入口，而「规则被谁在什么时候因为什么改过」正是规则
 * 可写的另一半。已删除的规则照样打得开——删除这件事本身也要可查（ADR-0027）。
 */
async function openChanges(rule: RiskRule): Promise<void> {
  changesRule.value = rule;
  changes.value = [];
  changesError.value = "";
  changesOpen.value = true;
  changesLoading.value = true;
  try {
    changes.value = await listRiskRuleChanges(rule.id);
  } catch (error) {
    changesError.value = errorMessage(error, "变更记录加载失败");
  } finally {
    changesLoading.value = false;
  }
}

// ---------------- 新建 / 编辑：同一个对话框 ----------------

type EditorMode = "create" | "edit";

const editorOpen = ref(false);
const editorMode = ref<EditorMode>("create");
const editorRule = ref<RiskRule | null>(null);
const editorError = ref("");

const draft = reactive({
  rule_name: "",
  category: "",
  description: "",
  alert_level: "" as AlertLevel | "",
  // 规则权重与窗长是数字框：空值(null)分别表示「用默认的 1.00」与「还没填」。
  weight: 1 as number | null,
  field: "",
  operator: "",
  threshold: {} as Record<string, string>,
  window_hours: null as number | null,
  reason: "",
});

// 判定形状在编辑态只读：改它等于换一条规则，历史预警与留痕都会顶着旧编号解释旧口径
// （ADR-0026）。阈值也在这四个控件里——编辑保存时一并提交：阈值有变化就单独走调阈值
// 接口，让阈值调整的留痕口径不变。
const isCreating = computed(() => editorMode.value === "create");
const shapeReadOnly = computed(() => !isCreating.value);
const editorTitle = computed(() =>
  isCreating.value ? "新建规则" : `编辑规则：${editorRule.value?.rule_code ?? ""}`,
);
const operatorChoicesForField = computed(() => operatorChoices(schema.value, draft.field));
const draftThresholdKeys = computed(() => thresholdKeys(schema.value, draft.operator));
const showWindowHours = computed(() => usesWindowHours(schema.value, draft.operator));
const fieldHint = computed(() => fieldSpec(schema.value, draft.field)?.description ?? "");
const rangeHint = computed(() => valueRangeHint(schema.value, draft.field));

/** 编辑态里阈值这四个格子相对这条规则现值有没有动过：没动就不发调阈值请求。 */
const thresholdChanged = computed(() => {
  const rule = editorRule.value;
  if (!rule) return false;
  const payload = thresholdPayload(schema.value, draft.operator, draft.threshold);
  const keys = new Set([...Object.keys(payload), ...Object.keys(rule.threshold)]);
  return [...keys].some((key) => (payload[key] ?? "").trim() !== String(rule.threshold[key] ?? "").trim());
});

/** 基本信息五项相对这条规则现值有没有动过：没动就不发 update。 */
const basicInfoChanged = computed(() => {
  const rule = editorRule.value;
  if (!rule) return false;
  return (
    draft.rule_name.trim() !== rule.rule_name ||
    draft.category !== rule.category ||
    draft.description.trim() !== rule.description ||
    draft.alert_level !== rule.alert_level ||
    (draft.weight ?? null) !== rule.weight
  );
});

// 换字段之后原来的算子可能不再被允许（比如从「交易金额」换到「产品标识」，`gte` 就不在
// 允许清单里了）。放着一个允许清单外的算子不提，只会在提交时被后端顶回来。
watch(
  () => draft.field,
  () => {
    if (!operatorChoicesForField.value.some((operator) => operator.key === draft.operator)) {
      draft.operator = "";
    }
  },
);

async function loadSchema(): Promise<void> {
  schemaError.value = "";
  try {
    schema.value = (await getRiskRuleSchema()) ?? null;
  } catch (error) {
    schemaError.value = errorMessage(error, "规则编辑器选项加载失败");
  }
}

/** 打开对话框前把草稿整份铺好：新建是一份空草稿，编辑是这条规则当前的样子。 */
function fillDraft(rule: RiskRule | null): void {
  editorRule.value = rule;
  editorError.value = "";
  draft.rule_name = rule?.rule_name ?? "";
  draft.category = rule?.category ?? "";
  draft.description = rule?.description ?? "";
  draft.alert_level = rule?.alert_level ?? "";
  // 新建时的规则权重默认 1.00，跟后端的默认值是同一个数。
  draft.weight = rule ? rule.weight : 1;
  draft.field = rule?.field ?? "";
  // 算子写在字段之后：上面那个 watcher 在下一个 tick 才跑，那时它已经是一个允许的算子了。
  draft.operator = rule?.operator ?? "";
  draft.threshold = { ...(rule?.threshold ?? {}) };
  draft.window_hours = rule?.window_hours ?? null;
  draft.reason = "";
}

function openCreate(): void {
  editorMode.value = "create";
  fillDraft(null);
  editorOpen.value = true;
}

function openEditor(rule: RiskRule): void {
  editorMode.value = "edit";
  fillDraft(rule);
  editorOpen.value = true;
}

async function submitEditor(): Promise<void> {
  editorError.value = "";
  const reason = draft.reason.trim();
  if (!reason) {
    editorError.value = isCreating.value ? "创建理由不能为空" : "修改理由不能为空";
    return;
  }
  // 数字框已经挡住了「非数字」与「小于 1」；挡不住的是「还没填」——那会落到 pydantic 的
  // `int | None` 上换回一句「参数错误」，而这里说得出是哪个控件少了东西。判断用真假而不是
  // `=== null`：数字框被清空时给回来的是 `undefined`。
  if (showWindowHours.value && !draft.window_hours) {
    editorError.value = "时间窗必须是正整数小时";
    return;
  }

  saving.value = true;
  try {
    if (isCreating.value) {
      await createRiskRule({
        rule_name: draft.rule_name.trim(),
        category: draft.category,
        description: draft.description.trim(),
        field: draft.field,
        operator: draft.operator,
        threshold: thresholdPayload(schema.value, draft.operator, draft.threshold),
        window_hours: showWindowHours.value ? (draft.window_hours ?? null) : null,
        alert_level: draft.alert_level as AlertLevel,
        weight: draft.weight,
        enabled: true,
        reason,
      });
      editorOpen.value = false;
      // 这句话是必须的：不回算历史交易（Q18），专员点完新建在预警列表里什么都看不到。
      ElMessage.success("规则已创建：新规则从下一笔交易起生效，历史交易不会被重新判定");
      // 新规则的编号是「曾经的最大值 + 1」，按编号升序排在最后一页——重取当前页不会
      // 把我刚建的那条挪到眼前，能立刻看见的是右侧摘要里的总条数。不回算的理由同上。
      await refresh();
    } else {
      const rule = editorRule.value;
      if (!rule) return;
      // 一次「编辑」按需提交：基本信息有变化才走 update，阈值有变化再单独走调阈值
      // 接口（阈值调整的留痕口径不变，共用编辑框里这条理由）。后端两个入口都会留痕，
      // 没变化也发就会留下一条前后快照一模一样的变更记录；两边都没动就明说，不发请求。
      if (!basicInfoChanged.value && !thresholdChanged.value) {
        editorError.value = "没有要修改的内容";
        return;
      }
      let current = rule;
      if (basicInfoChanged.value) {
        current = await updateRiskRule(rule.id, {
          rule_name: draft.rule_name.trim(),
          category: draft.category,
          description: draft.description.trim(),
          alert_level: draft.alert_level as AlertLevel,
          weight: draft.weight,
          reason,
        });
        // 同步到 editorRule：接下来阈值那步失败时，重试只会重发失败的那半步。
        editorRule.value = current;
      }
      replaceRule(
        thresholdChanged.value
          ? await setRiskRuleThreshold(
              rule.id,
              thresholdPayload(schema.value, draft.operator, draft.threshold),
              reason,
            )
          : current,
      );
      editorOpen.value = false;
      ElMessage.success("规则已更新");
    }
  } catch (error) {
    editorError.value = errorMessage(error, isCreating.value ? "创建失败" : "保存失败");
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  void reset();
  // 编辑器要的下拉项只有写操作才用得上：非风控专员进去也是只读表格，不必打这个请求。
  if (canManage.value) void loadSchema();
});

useTabSummary(
  (value) => emit("summary", value),
  () => ({
    // 「共 N 条」是过滤后的总数，不是本页条数；启用条数只数得到本页，因此说清是「本页」，
    // 否则分页一开，这个数字会随翻页变。「含已删除」要说出来：那个总数里混着已经不算数的行。
    headline: `共 ${total.value} 条规则${includeDeleted.value ? "（含已删除）" : ""} · 本页 ${enabledCount.value} 条启用`,
    count: total.value,
  }),
);
</script>

<template>
  <div class="rules">
    <PanelCard title="规则管理">
      <div class="rules__toolbar">
        <el-checkbox v-model="includeDeleted" name="include-deleted" data-testid="include-deleted">
          显示已删除
        </el-checkbox>
        <el-button
          type="primary"
          name="create-rule"
          data-testid="create-rule"
          :disabled="!canManage || !schema"
          @click="openCreate"
        >
          新建规则
        </el-button>
      </div>

      <p
        v-if="ruleError || actionError || schemaError"
        class="rules__error"
        role="alert"
        data-testid="rule-error"
      >
        {{ ruleError || actionError || schemaError }}
      </p>
      <p v-if="!loading && !rules.length && !ruleError" class="rules__empty">还没有风控规则。</p>
      <p v-else-if="!canManage" class="rules__hint" data-testid="rule-read-only">
        当前角色只能查看规则；启停与阈值调整由风控专员完成。
      </p>

      <el-table
        v-if="rules.length"
        :data="rules"
        :row-class-name="({ row }: { row: RiskRule }) => (isDeleted(row) ? 'rules__row--deleted' : '')"
        data-testid="rules-table"
      >
        <el-table-column label="编号" min-width="110">
          <template #default="{ row }">
            <span>{{ row.rule_code }}</span>
            <el-tag v-if="isDeleted(row)" type="info" size="small" class="rules__deleted-tag">
              已删除
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="规则" prop="rule_name" min-width="130" />
        <el-table-column label="判定字段" prop="field_label" min-width="90" />
        <el-table-column label="算子" prop="operator_label" min-width="100" />
        <el-table-column label="阈值" prop="threshold_text" min-width="100" />
        <el-table-column label="启停" min-width="70">
          <template #default="{ row }">
            <!-- 已删除的行不留启停控件：删除是终态，撤销它没有入口（要停用请用启停）。 -->
            <el-switch
              v-if="!isDeleted(row)"
              :model-value="row.enabled"
              :disabled="!canManage"
              :before-change="() => toggleRule(row)"
              data-testid="rule-enabled"
            />
            <span v-else class="rules__hint">—</span>
          </template>
        </el-table-column>
        <!--
          操作列的 min-width 按角色取下限：专员是三个默认小按钮（查看变更记录 / 编辑 / 删除）
          一行放得下（约 250px），非专员只剩「查看变更记录」一个（约 130px）。
          旧版固定 310px 是按四个按钮给的——非专员那一列右侧空出一大截，而各列
          min-width 合计（970px）又顶出容器，平白多出一条横向滚动条。
          为了给默认按钮腾宽度，其余各列也按表头/内容宽度收紧：
          110 + 130 + 90 + 100 + 100 + 70 + 250 = 850px，在「1200px 视口 + 侧栏展开 +
          检查器收起」的可用宽度（873px）内，专员与非专员两个视图都不出横向滚动条。
        -->
        <el-table-column label="操作" :min-width="canManage ? 250 : 130">
          <template #default="{ row }">
            <el-button size="small" data-testid="view-changes" @click="openChanges(row)">
              查看变更记录
            </el-button>
            <template v-if="canManage && !isDeleted(row)">
              <el-button size="small" data-testid="edit-rule" @click="openEditor(row)">编辑</el-button>
              <el-button size="small" data-testid="delete-rule" @click="removeRule(row)">删除</el-button>
            </template>
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

    <el-dialog v-model="editorOpen" :title="editorTitle" width="560px">
      <div class="editor" data-testid="rule-editor">
        <label v-if="editorMode === 'edit'" class="editor__field">
          <span class="editor__label">规则编号</span>
          <el-input :model-value="editorRule?.rule_code ?? ''" disabled data-testid="editor-code" />
        </label>

        <label class="editor__field">
          <span class="editor__label">规则名称（必填）</span>
          <el-input v-model="draft.rule_name" name="rule-name" data-testid="editor-name" />
        </label>

        <label class="editor__field">
          <span class="editor__label">规则分类（必填）</span>
          <el-select
            v-model="draft.category"
            name="rule-category"
            data-testid="editor-category"
            placeholder="选择规则分类"
          >
            <el-option v-for="category in schema?.categories ?? []" :key="category" :label="category" :value="category" />
          </el-select>
        </label>

        <label class="editor__field">
          <span class="editor__label">判定字段（必填）</span>
          <el-select
            v-model="draft.field"
            name="rule-field"
            data-testid="editor-field"
            :disabled="shapeReadOnly"
            placeholder="选择字段"
          >
            <el-option v-for="field in schema?.fields ?? []" :key="field.key" :label="field.label" :value="field.key" />
          </el-select>
          <span v-if="fieldHint" class="editor__hint">{{ fieldHint }}</span>
        </label>

        <label class="editor__field">
          <span class="editor__label">算子（必填）</span>
          <el-select
            v-model="draft.operator"
            name="rule-operator"
            data-testid="editor-operator"
            :disabled="shapeReadOnly"
            placeholder="选择算子"
          >
            <el-option
              v-for="operator in operatorChoicesForField"
              :key="operator.key"
              :label="`${operator.label}（${operator.symbol}）`"
              :value="operator.key"
            />
          </el-select>
        </label>

        <label v-if="showWindowHours" class="editor__field">
          <span class="editor__label">时间窗（小时，必填）</span>
          <el-input-number
            v-model="draft.window_hours"
            name="rule-window"
            data-testid="editor-window"
            :min="1"
            :step="1"
            :precision="0"
            :disabled="shapeReadOnly"
          />
        </label>

        <div class="editor__field">
          <span class="editor__label">阈值（必填）</span>
          <!-- 输入框的数量与键名随算子的 `threshold_keys` 走：`gte` 一个、`between` 两个。 -->
        <!-- 判定形状（字段 / 算子 / 时间窗）在编辑态只读，阈值在两种模式下都可改。 -->
          <div class="editor__threshold">
            <label v-for="key in draftThresholdKeys" :key="key" class="editor__threshold-item">
              <span class="editor__hint">{{ thresholdKeyLabel(key) }}</span>
              <el-input
                v-model="draft.threshold[key]"
                :name="`rule-threshold-${key}`"
                :data-testid="`editor-threshold-${key}`"
              />
            </label>
          </div>
          <span v-if="rangeHint" class="editor__hint">值域：{{ rangeHint }}</span>
        </div>

        <label class="editor__field">
          <span class="editor__label">预警等级（必填）</span>
          <el-select v-model="draft.alert_level" name="rule-alert-level" data-testid="editor-alert-level">
            <el-option v-for="level in ALERT_LEVELS" :key="level" :label="level" :value="level" />
          </el-select>
        </label>

        <label class="editor__field">
          <span class="editor__label">规则权重</span>
          <el-input-number
            v-model="draft.weight"
            name="rule-weight"
            data-testid="editor-weight"
            :min="0.5"
            :max="5"
            :step="0.1"
            :precision="2"
          />
          <span class="editor__hint">默认 1.00，区间 0.50 到 5.00</span>
        </label>

        <label class="editor__field">
          <span class="editor__label">规则描述</span>
          <el-input
            v-model="draft.description"
            name="rule-description"
            data-testid="editor-description"
            placeholder="留空则按判定形状自动生成"
          />
        </label>

        <p v-if="shapeReadOnly" class="editor__hint" data-testid="shape-note">
          要改判定形状请删除后重建，阈值可在上方直接调整（保存时生效并单独留痕）。
        </p>

        <label class="editor__field">
          <span class="editor__label">
            {{ isCreating ? "创建理由（必填）" : "修改理由（必填）" }}
          </span>
          <el-input
            v-model="draft.reason"
            name="rule-reason"
            type="textarea"
            :rows="3"
            data-testid="editor-reason"
          />
        </label>

        <p v-if="editorError" class="rules__error" role="alert" data-testid="editor-error">
          {{ editorError }}
        </p>
      </div>

      <template #footer>
        <el-button @click="editorOpen = false">取消</el-button>
        <el-button type="primary" data-testid="save-rule" :loading="saving" @click="submitEditor">
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="changesOpen"
      :title="changesRule ? `变更记录：${changesRule.rule_code}` : '变更记录'"
      width="720px"
    >
      <p v-if="changesError" class="rules__error" role="alert" data-testid="changes-error">
        {{ changesError }}
      </p>
      <p v-else-if="!changesLoading && !changes.length" class="rules__hint" data-testid="changes-empty">
        这条规则还没有变更记录。
      </p>

      <el-table v-if="changes.length" :data="changes" data-testid="rule-changes">
        <el-table-column label="时间" min-width="150">
          <template #default="{ row }">{{ formatDateTime(row.changed_at) }}</template>
        </el-table-column>
        <el-table-column label="变更类型" prop="change_type" min-width="90" />
        <el-table-column label="操作人" prop="changed_by_name" min-width="90" />
        <el-table-column label="变更内容" min-width="240">
          <template #default="{ row }">
            <span data-testid="change-diff">
              {{ formatValue(row.old_value) }} → {{ formatValue(row.new_value) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="理由" prop="reason" min-width="140" />
      </el-table>

      <template #footer>
        <el-button data-testid="close-changes" @click="changesOpen = false">关闭</el-button>
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

.rules__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wm-space-3);
  margin-bottom: var(--wm-space-3);
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

.rules__deleted-tag {
  margin-left: var(--wm-space-2);
}

/* 已删除的行置灰只读：它还在列表里是为了可查，不是为了还能改。 */
.rules :deep(.rules__row--deleted) {
  color: var(--wm-text-muted);
}

.editor {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.editor__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
}

.editor__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.editor__hint {
  color: var(--wm-text-muted);
  font-size: 0.78rem;
  line-height: 1.6;
}

.editor__threshold {
  display: flex;
  gap: var(--wm-space-3);
}

.editor__threshold-item {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--wm-space-1);
}
</style>
