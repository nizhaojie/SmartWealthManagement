<script setup lang="ts">
import { ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { PanelCard } from "@wealth/shared";
import type { CustomerListItem } from "../customers/types";
import { errorMessage, formatDateTime, formatMoney } from "../format";
import { listCustomerAdvice, startAdvice } from "./api";
import { DIRECTIONS, type OperationAdviceProgress } from "./types";
import { customerStatusTagType, reviewStatusTagType } from "./view";

/**
 * 客户经理为客户发起操作建议，并看他发起过的建议走到哪一步了。
 *
 * 入口放在客户关系模块里——那是客户经理唯一的地盘（角色可见性留在应用内）。这里
 * **没有放行 / 驳回**：发起与放行是两件事，放行是理财顾问的资质（CONTEXT「客户经理」）。
 * 他读得到、留言得了，这两件事都发生在审核页上（本页的「查看」）。
 *
 * 产品、金额与理由由业务操作 Agent 在候选池内给出，因此这里只让客户经理选**方向**
 * ——方向是他的判断，产品与理由是算出来的（#06 的发起场景）。
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

// 进度跟着选中的客户走，由状态变化驱动而不是由下拉的 change 事件驱动：
// 「换了一位客户」才是要重新读进度的那件事。
watch(customerId, (value) => {
  progress.value = [];
  progressError.value = "";
  if (value !== null) {
    void loadProgress(value);
  }
});

async function submit(): Promise<void> {
  if (customerId.value === null) return;
  submitting.value = true;
  startError.value = "";
  try {
    await startAdvice(customerId.value, direction.value);
    ElMessage.success("已发起，等待理财顾问审核");
    await loadProgress(customerId.value);
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
      <el-button
        type="primary"
        name="start-advice"
        data-testid="start-advice"
        :disabled="customerId === null"
        :loading="submitting"
        @click="submit"
      >
        发起建议
      </el-button>
    </div>

    <p v-if="startError" class="advice-start__error" role="alert" data-testid="start-advice-error">
      {{ startError }}
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
