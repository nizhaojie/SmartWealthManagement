<script setup lang="ts">
/**
 * 「我的方案」：投顾内容在客户侧的送达面。
 *
 * 两个分区不合成一条时间线：直接生成的方案没有对应请求（内部端的「为客户发起
 * 生成」传 `advisory_request_id=null`），以请求为主键会出现孤儿；而「等待中」
 * 与「已出具」是两种不同的状态，混排会让客户分不清哪条在等他、哪条已经好了。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ApiError, PageHeader, PanelCard } from "@wealth/shared";
import AdvisoryRequestList from "./AdvisoryRequestList.vue";
import { listAdvisoryRequests, listReleasedPlans } from "./api";
import { formatDateTime } from "./timeliness";
import type { AdvisoryRequest, ReleasedPlan } from "./types";

const router = useRouter();

const plans = ref<ReleasedPlan[]>([]);
const plansLoading = ref(true);
const plansError = ref("");

const requests = ref<AdvisoryRequest[]>([]);
// 「请求拉取成功」与「请求为空」要分得开：接口故障不该被说成「你还没提过请求」。
const requestsLoaded = ref(false);
const requestsError = ref("");

// 两级空状态：无定稿但有请求 → 空状态位置直接渲染请求进度；两者都无 → 引导去产品筛选。
const showOnboarding = computed(
  () =>
    !plansLoading.value &&
    !plansError.value &&
    plans.value.length === 0 &&
    requestsLoaded.value &&
    requests.value.length === 0,
);

async function loadPlans(): Promise<void> {
  plansLoading.value = true;
  plansError.value = "";
  try {
    plans.value = (await listReleasedPlans()).plans;
  } catch (error) {
    plans.value = [];
    plansError.value = error instanceof ApiError ? error.message : "方案加载失败";
  } finally {
    plansLoading.value = false;
  }
}

async function loadRequests(): Promise<void> {
  requestsError.value = "";
  try {
    requests.value = (await listAdvisoryRequests()).requests;
    requestsLoaded.value = true;
  } catch (error) {
    // 请求进度拉不到不影响已放行的方案，但也不能一声不响：尚无定稿时它就是
    // 页面上唯一该有内容的位置，留白会让客户以为系统坏了（Q6 不留一块空白）。
    requestsError.value =
      error instanceof ApiError ? `方案请求进度加载失败：${error.message}` : "方案请求进度加载失败";
  }
}

function openPlan(finalId: number): void {
  void router.push({ name: "advisory-plan", params: { finalId } });
}

function goProducts(): void {
  void router.push({ name: "products" });
}

onMounted(() => {
  void Promise.all([loadPlans(), loadRequests()]);
});
</script>

<template>
  <div class="plans">
    <PageHeader title="我的方案" :breadcrumb="['客户视图', '我的方案']" />

    <p v-if="plansLoading" class="plans__status">正在加载方案…</p>

    <PanelCard v-else-if="plans.length" title="已放行方案">
      <ul class="plans__list" data-testid="released-plans">
        <li v-for="plan in plans" :key="plan.id">
          <button
            type="button"
            class="plan-row"
            name="open-plan"
            data-testid="released-plan"
            :data-plan-id="plan.id"
            @click="openPlan(plan.id)"
          >
            <span class="plan-row__time" data-testid="plan-released-at">
              出具时间：{{ formatDateTime(plan.released_at) }}
            </span>
            <span class="plan-row__advisor" data-testid="plan-advisor">
              出具顾问：{{ plan.advisor_name ?? "—" }}
            </span>
            <span class="plan-row__count" data-testid="plan-product-count">
              产品数：{{ plan.candidates.length }}
            </span>
          </button>
        </li>
      </ul>
    </PanelCard>

    <p v-else-if="plansError" class="plans__error" role="alert" data-testid="plans-error">
      {{ plansError }}
    </p>

    <AdvisoryRequestList :requests="requests" />

    <p v-if="requestsError" class="plans__error" role="alert" data-testid="requests-error">
      {{ requestsError }}
    </p>

    <PanelCard v-if="showOnboarding" title="还没有收到方案">
      <p class="plans__empty" data-testid="plans-empty">
        还没有提交过方案请求。在产品筛选里挑好条件后，可以让顾问为你出具一份方案。
      </p>
      <el-button name="go-products" data-testid="go-products" @click="goProducts">
        前往产品筛选
      </el-button>
    </PanelCard>
  </div>
</template>

<style scoped>
.plans {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.plans__list {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

/* 整行可点：一份方案是一行摘要，点进去才是详情。 */
.plan-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--wm-space-2) var(--wm-space-4);
  width: 100%;
  padding: var(--wm-space-3) var(--wm-space-4);
  /* 方案行的 1px 描边（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border-hairline);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-subtle);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.plan-row:hover {
  border-color: var(--wm-color-primary);
  background-color: var(--wm-color-primary-tint);
}

.plan-row__time {
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.plan-row__advisor,
.plan-row__count {
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.plans__status,
.plans__empty {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.75;
}

.plans__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
