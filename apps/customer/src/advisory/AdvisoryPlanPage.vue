<script setup lang="ts">
/**
 * 「我的方案」：投顾内容在客户侧的送达面。
 *
 * 两个分区不合成一条时间线：直接生成的方案没有对应请求（内部端的「为客户发起
 * 生成」传 `advisory_request_id=null`），以请求为主键会出现孤儿；而「等待中」
 * 与「已出具」是两种不同的状态，混排会让客户分不清哪条在等他、哪条已经好了。
 *
 * 两个分区各自一页（ADR-0024）：翻方案不会重取请求，翻请求也不会重取方案。
 * `total` 都取服务端给的过滤后总数，空状态因此判的是「一份都没有」而不是
 * 「这一页没有」。
 */
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { PageHeader, PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import AdvisoryRequestList from "./AdvisoryRequestList.vue";
import { listAdvisoryRequests, listReleasedPlans } from "./api";
import { formatDateTime } from "./timeliness";
import type { AdvisoryRequest, ReleasedPlan } from "./types";

const router = useRouter();

const {
  items: plans,
  total: plansTotal,
  page: plansPage,
  pageSize: plansPageSize,
  loading: plansLoading,
  errorMessage: plansError,
  goTo: goToPlans,
  reset: resetPlans,
} = usePagination<ReleasedPlan>((query) => listReleasedPlans(query), {
  failureMessage: "方案加载失败",
});

// 取不到时给一句「这一段怎么了」：只留下服务端那句话，客户经理分不清是方案还是
// 请求进度拉不到（两段共用同一个失败横幅的位置）。
const REQUESTS_FAILURE_HINT = "暂时取不到";

const {
  items: requests,
  total: requestsTotal,
  page: requestsPage,
  pageSize: requestsPageSize,
  loading: requestsLoading,
  errorMessage: requestsError,
  goTo: goToRequests,
  reset: resetRequests,
} = usePagination<AdvisoryRequest>((query) => listAdvisoryRequests(query), {
  failureMessage: REQUESTS_FAILURE_HINT,
});

/** 「拉取失败」与「什么都没有」要分得开：失败不该被说成「你还没提过请求」。 */
const requestsFailure = computed(() =>
  requestsError.value ? `方案请求进度加载失败：${requestsError.value}` : "",
);

// 两级空状态：无定稿但有请求 → 空状态位置直接渲染请求进度；两者都无 → 引导去产品筛选。
const showOnboarding = computed(
  () =>
    !plansLoading.value &&
    !plansError.value &&
    plansTotal.value === 0 &&
    !requestsLoading.value &&
    !requestsError.value &&
    requestsTotal.value === 0,
);

function openPlan(finalId: number): void {
  void router.push({ name: "advisory-plan", params: { finalId } });
}

function goProducts(): void {
  void router.push({ name: "products" });
}

onMounted(() => {
  void Promise.all([resetPlans(), resetRequests()]);
});
</script>

<template>
  <div class="plans">
    <PageHeader title="我的方案" :breadcrumb="['客户视图', '我的方案']" />

    <PanelCard v-if="plansLoading || plansTotal > 0" title="已放行方案">
      <p v-if="plansLoading" class="plans__status">正在加载方案…</p>
      <!-- 本页为空而总数不为零（越界页）时不写「暂无」：那是两句不同的话。 -->
      <ul v-else-if="plans.length" class="plans__list" data-testid="released-plans">
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

      <!-- 取不到时 `total` 归零，分页条与列表同进同退：一份方案都没有时它不该出现。 -->
      <PaginationBar
        v-if="plansTotal > 0"
        :total="plansTotal"
        :page="plansPage"
        :page-size="plansPageSize"
        :disabled="plansLoading"
        @update:page="goToPlans"
      />
    </PanelCard>

    <p v-else-if="plansError" class="plans__error" role="alert" data-testid="plans-error">
      {{ plansError }}
    </p>

    <AdvisoryRequestList
      :requests="requests"
      :total="requestsTotal"
      :page="requestsPage"
      :page-size="requestsPageSize"
      :loading="requestsLoading"
      @update:page="goToRequests"
    />

    <p v-if="requestsFailure" class="plans__error" role="alert" data-testid="requests-error">
      {{ requestsFailure }}
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
