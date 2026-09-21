<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { PanelCard } from "@wealth/shared";
import type { CustomerListItem } from "../customers/types";
import { errorMessage, formatDateTime, formatMoney } from "../format";
import { listAdviceOptions, listCustomerAdvice, startAdvice } from "./api";
import { DIRECTIONS, type AdviceOption, type OperationAdviceProgress } from "./types";
import { customerStatusTagType, reviewStatusTagType } from "./view";

/**
 * 客户经理为客户发起操作建议，并看他发起过的建议走到哪一步了。
 *
 * 入口放在客户关系模块里——那是客户经理唯一的地盘（角色可见性留在应用内）。这里
 * **没有放行 / 驳回**：发起与放行是两件事，放行是理财顾问的资质（CONTEXT「客户经理」）。
 * 他读得到、留言得了，这两件事都发生在审核页上（本页的「查看」）。
 *
 * 产品与金额 / 份额由客户经理选定（ADR-0021）：方向 → 产品（候选池内选）→ 金额（申购）
 * 或份额（赎回）。可选项由后端算好（`operation-advice-options`），这里只读只渲染——
 * 不按方向过滤、不算买不买得起，否则选品规则被表达两次，漂移的表现是「下拉里有这只
 * 产品，一提交被拒」，而不会有任何断言失败。
 */
defineProps<{ customers: CustomerListItem[] }>();

const router = useRouter();

const customerId = ref<number | null>(null);
const direction = ref<string>(DIRECTIONS[0]);
const submitting = ref(false);
const startError = ref("");

const progress = ref<OperationAdviceProgress[]>([]);
const progressLoading = ref(false);
const progressError = ref("");

// 可选项：跟着「客户 + 方向」走，两个字段任一变化都要重取。
const options = ref<AdviceOption[]>([]);
const optionsLoading = ref(false);
const optionsError = ref("");
const productCode = ref<string | null>(null);
const quantity = ref("");

// 进度表跟着选中的客户走；加载失败时不留上一位置客户的进度（那是别人的数据）。
async function loadProgress(nextCustomerId: number): Promise<void> {
  progressLoading.value = true;
  progressError.value = "";
  progress.value = [];
  try {
    progress.value = await listCustomerAdvice(nextCustomerId);
  } catch (error) {
    progressError.value = errorMessage(error, "建议进度加载失败");
  } finally {
    progressLoading.value = false;
  }
}

// 可选项跟着「客户 + 方向」走：换了任何一头，先清掉上一份结果（那是另一位客户或
// 另一个方向的产品），再按后端算好的列表重取。
async function loadOptions(nextCustomerId: number, nextDirection: string): Promise<void> {
  optionsLoading.value = true;
  optionsError.value = "";
  options.value = [];
  try {
    const result = await listAdviceOptions(nextCustomerId, nextDirection);
    options.value = result.products;
  } catch (error) {
    optionsError.value = errorMessage(error, "可选项加载失败");
  } finally {
    optionsLoading.value = false;
  }
}

// 进度跟着选中的客户走，由状态变化驱动而不是由下拉的 change 事件驱动：
// 「换了一位客户」才是要重新读进度的那件事。
watch(customerId, (value) => {
  progress.value = [];
  progressError.value = "";
  if (value !== null) {
    void loadProgress(value);
  }
});

// 可选项的驱动是「客户 + 方向」这一对：选完客户或切换方向都要重取，选中的产品与
// 填的金额 / 份额一并清掉——那是针对上一份可选项的选择，不能带到下一份里。
watch([customerId, direction], ([nextCustomerId, nextDirection]) => {
  options.value = [];
  optionsError.value = "";
  productCode.value = null;
  quantity.value = "";
  if (nextCustomerId !== null) {
    void loadOptions(nextCustomerId, nextDirection);
  }
});

const isPurchase = computed(() => direction.value === "申购");
const quantityLabel = computed(() => (isPurchase.value ? "申购金额（元）" : "赎回份额"));

const selectedOption = computed(
  () => options.value.find((option) => option.product_code === productCode.value) ?? null,
);

// 金额 / 份额的合法区间由后端给：申购是 `min_amount` / `max_amount`，赎回是可赎回
// 份额（`max_shares`）。前端只用这两个数做输入约束，不复算费率。
const minQuantity = computed(() => {
  if (!selectedOption.value) return undefined;
  return isPurchase.value ? selectedOption.value.min_amount : "0";
});
const maxQuantity = computed(() => {
  if (!selectedOption.value) return undefined;
  return isPurchase.value ? selectedOption.value.max_amount : selectedOption.value.max_shares;
});

// 空态沿用既有两句文案：候选池为空与「全部买不起」是两种不同的「没得选」，经理要
// 知道是哪种。买不起的项仍然列出但禁用（不藏掉），只有一项都买不起时这里才说「都买不起」。
const emptyMessage = computed(() => {
  if (customerId.value === null) return null;
  if (!options.value.length) return "该客户当前没有合规产品可选";
  if (options.value.every((option) => !option.affordable)) {
    return "可用余额不足以申购候选池内的任何产品";
  }
  return null;
});

// 有得选、且没在加载 / 报错时，才渲染产品与金额 / 份额两个字段。
const showProduct = computed(
  () =>
    customerId.value !== null &&
    !optionsLoading.value &&
    !optionsError.value &&
    !emptyMessage.value,
);

const canSubmit = computed(
  () => customerId.value !== null && productCode.value !== null && quantity.value.trim() !== "",
);

// 选项文案含五要素：产品名 + 代码 + 风险等级 + 期限 + 起投金额（Q13）。买不起的
// 项额外注明原因，与「禁用」一起把「这只为什么不能选」说清楚。
function optionLabel(option: AdviceOption): string {
  const base = `${option.product_name}（${option.product_code}）· ${option.risk_level} · ${option.term_days} 天 · 起投 ${option.min_amount} 元`;
  return option.affordable ? base : `${base}（可用余额不足）`;
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return;
  submitting.value = true;
  startError.value = "";
  try {
    await startAdvice(
      customerId.value as number,
      direction.value,
      productCode.value as string,
      quantity.value.trim(),
    );
    ElMessage.success("已发起，等待理财顾问审核");
    await loadProgress(customerId.value as number);
  } catch (error) {
    startError.value = errorMessage(error, "发起建议失败");
  } finally {
    submitting.value = false;
  }
}

function openAdvice(adviceId: number): void {
  void router.push({ name: "operation-advice-review", params: { adviceId } });
}
</script>

<template>
  <PanelCard title="操作建议">
    <div class="advice-start">
      <label class="advice-start__field">
        <span class="advice-start__label">客户</span>
        <el-select
          v-model="customerId"
          name="advice-customer"
          placeholder="选择客户"
          data-testid="advice-customer-select"
        >
          <el-option
            v-for="customer in customers"
            :key="customer.id"
            :label="customer.real_name"
            :value="customer.id"
          />
        </el-select>
      </label>
      <label class="advice-start__field">
        <span class="advice-start__label">建议方向</span>
        <el-select v-model="direction" name="advice-direction" data-testid="advice-direction-select">
          <el-option v-for="option in DIRECTIONS" :key="option" :label="option" :value="option" />
        </el-select>
      </label>
      <label v-if="showProduct" class="advice-start__field">
        <span class="advice-start__label">产品</span>
        <el-select
          v-model="productCode"
          name="advice-product"
          placeholder="选择产品"
          data-testid="advice-product-select"
        >
          <el-option
            v-for="option in options"
            :key="option.product_code"
            :label="optionLabel(option)"
            :value="option.product_code"
            :disabled="!option.affordable"
          />
        </el-select>
      </label>
      <label v-if="showProduct" class="advice-start__field">
        <span class="advice-start__label">{{ quantityLabel }}</span>
        <el-input
          v-model="quantity"
          name="advice-quantity"
          type="number"
          :min="minQuantity"
          :max="maxQuantity"
          placeholder="请填写"
          data-testid="advice-quantity-input"
        />
      </label>
      <el-button
        type="primary"
        name="start-advice"
        data-testid="start-advice"
        :disabled="!canSubmit"
        :loading="submitting"
        @click="submit"
      >
        发起建议
      </el-button>
    </div>

    <p v-if="startError" class="advice-start__error" role="alert" data-testid="start-advice-error">
      {{ startError }}
    </p>

    <p
      v-if="optionsLoading"
      class="advice-start__hint"
      data-testid="advice-options-loading"
    >
      正在加载可选项…
    </p>
    <p
      v-else-if="optionsError"
      class="advice-start__error"
      role="alert"
      data-testid="advice-options-error"
    >
      {{ optionsError }}
    </p>
    <p v-else-if="emptyMessage" class="advice-start__hint" data-testid="advice-options-empty">
      {{ emptyMessage }}
    </p>

    <p v-if="customerId === null" class="advice-start__hint" data-testid="advice-progress-hint">
      选择一位客户后可发起建议，并查看他名下已发起的建议进度。
    </p>
    <template v-else>
      <p
        v-if="progressError"
        class="advice-start__error"
        role="alert"
        data-testid="advice-progress-error"
      >
        {{ progressError }}
      </p>
      <p
        v-else-if="!progressLoading && !progress.length"
        class="advice-start__hint"
        data-testid="advice-progress-empty"
      >
        还没有为他发起过建议。
      </p>
      <el-table
        v-if="progress.length"
        :data="progress"
        class="advice-start__table"
        data-testid="advice-progress-table"
      >
        <el-table-column label="产品" min-width="150">
          <template #default="{ row }">{{ row.product_name ?? row.product_code }}</template>
        </el-table-column>
        <el-table-column label="方向" prop="direction" width="90" />
        <el-table-column label="金额" width="130">
          <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="审核进度" width="110">
          <template #default="{ row }">
            <el-tag :type="reviewStatusTagType(row.review_status)" size="small">
              {{ row.review_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="客户决定" width="120">
          <template #default="{ row }">
            <el-tag
              v-if="row.customer_status"
              :type="customerStatusTagType(row.customer_status)"
              size="small"
            >
              {{ row.customer_status }}
            </el-tag>
            <span v-else class="advice-start__hint">—</span>
          </template>
        </el-table-column>
        <el-table-column label="发起时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.generated_at) }}</template>
        </el-table-column>
        <el-table-column label="查看" width="90">
          <template #default="{ row }">
            <el-button
              size="small"
              name="open-advice"
              data-testid="open-advice"
              @click="openAdvice(row.id)"
            >
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>
  </PanelCard>
</template>

<style scoped>
.advice-start {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--wm-space-3) var(--wm-space-4);
}

.advice-start__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: calc(var(--wm-space-6) * 5);
}

.advice-start__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.advice-start__table {
  margin-top: var(--wm-space-3);
}

.advice-start__hint {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.advice-start__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
