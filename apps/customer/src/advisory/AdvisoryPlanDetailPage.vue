<script setup lang="ts">
/**
 * 一份方案的详情：出具顾问、放行时间、时效提示、产品清单、配置建议、免责声明。
 *
 * 页面只渲染客户送达视图里的东西——综合得分、排序依据与推荐理由不在这里，
 * 它们压根不在响应体上（ADR-0016）。裁剪发生在服务端，本页不是它的替代品。
 */
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, PageHeader, PanelCard } from "@wealth/shared";
import { getReleasedPlan } from "./api";
import { formatDateTime, timelinessText } from "./timeliness";
import type { ReleasedPlan } from "./types";

const route = useRoute();
const router = useRouter();

const finalId = computed(() => String(route.params.finalId));

const plan = ref<ReleasedPlan | null>(null);
const loading = ref(true);
const errorMessage = ref("");

const releasedAtText = computed(() => (plan.value ? formatDateTime(plan.value.released_at) : ""));
// 不设硬过期，只把「这份结论有多新」写出来（Q7）。
const timeliness = computed(() => (plan.value ? timelinessText(plan.value.released_at) : ""));

async function load(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  plan.value = null;
  try {
    plan.value = await getReleasedPlan(finalId.value);
  } catch (error) {
    // 不属于自己的 id 与不存在同义（服务端回 404，不确认他人资源是否存在）。
    // 服务端那句「尚无已放行的方案」是给「最新一份」用的：挂在详情页上，客户
    // 明明有别的方案却读到「还没有方案」，与事实相反。
    errorMessage.value =
      error instanceof ApiError
        ? error.code === 404
          ? "打不开这份方案：它不存在，或不属于当前账号。"
          : error.message
        : "方案加载失败";
  } finally {
    loading.value = false;
  }
}

function backToPlans(): void {
  void router.push({ name: "advisory" });
}

watch(finalId, load, { immediate: true });
</script>

<template>
  <div class="plan-detail">
    <PageHeader title="方案详情" :breadcrumb="['客户视图', '我的方案', '方案详情']">
      <template #actions>
        <el-button
          size="small"
          name="back-to-plans"
          data-testid="back-to-plans"
          @click="backToPlans"
        >
          返回我的方案
        </el-button>
      </template>
    </PageHeader>

    <p v-if="loading" class="plan-detail__hint">正在加载方案…</p>

    <p v-else-if="errorMessage" class="plan-detail__error" role="alert" data-testid="plan-error">
      {{ errorMessage }}
    </p>

    <template v-else-if="plan">
      <PanelCard title="出具信息">
        <p class="plan-detail__row" data-testid="plan-advisor">
          出具顾问：{{ plan.advisor_name ?? "—" }}
        </p>
        <p class="plan-detail__row" data-testid="plan-released-at">放行时间：{{ releasedAtText }}</p>
        <p class="plan-detail__timeliness" data-testid="plan-timeliness">
          {{ timeliness }}，本方案基于出具时点的画像与市场数据。
        </p>
      </PanelCard>

      <PanelCard title="配置建议">
        <ul class="allocation" data-testid="plan-allocation">
          <li v-for="(value, key) in plan.allocation_suggestion" :key="key">{{ key }}：{{ value }}%</li>
        </ul>
      </PanelCard>

      <PanelCard title="产品清单">
        <div class="table-wrap">
          <table data-testid="plan-candidates">
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                <th>类型</th>
                <th>产品风险等级</th>
                <th>业绩基准</th>
                <th>期限（天）</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="product in plan.candidates"
                :key="product.product_code"
                :data-product-code="product.product_code"
              >
                <td>{{ product.product_code }}</td>
                <td>{{ product.product_name }}</td>
                <td>{{ product.product_type }}</td>
                <td>{{ product.risk_level }}</td>
                <td>{{ product.expected_return }}</td>
                <td>{{ product.term_days }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </PanelCard>

      <p v-if="plan.disclaimer" class="plan-detail__disclaimer" data-testid="plan-disclaimer">
        {{ plan.disclaimer }}
      </p>
    </template>
  </div>
</template>

<style scoped>
.plan-detail {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.plan-detail__row {
  margin: 0 0 var(--wm-space-1);
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
}

.plan-detail__timeliness {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.75;
}

.plan-detail__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.plan-detail__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

/* 免责声明：说明块左侧 3px 强调条，与产品筛选页的「不是推荐」同一形态 */
.plan-detail__disclaimer {
  margin: 0;
  padding: var(--wm-space-2) var(--wm-space-3);
  border-left: 3px solid var(--wm-color-primary);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  line-height: 1.75;
}

.allocation {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  margin: 0;
  padding-left: var(--wm-space-4);
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.8;
  font-variant-numeric: tabular-nums;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 表格行的 1px 分隔细线（令牌纪律声明的极少数例外） */
  border-bottom: 1px solid var(--wm-border-hairline);
  text-align: left;
  font-size: 0.85rem;
  white-space: nowrap;
}

th {
  color: var(--wm-text-muted);
  font-weight: 600;
}

td {
  color: var(--wm-text-primary);
  font-variant-numeric: tabular-nums;
}
</style>
