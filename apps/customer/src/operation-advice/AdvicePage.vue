<script setup lang="ts">
/**
 * 「我的建议」：客户经理发起、理财顾问放行后送达客户的操作建议，是等客户做决定的事。
 *
 * 它与「我的方案」是两处：方案是资料库（只把已放行的内容回看一遍），这里是收件箱
 * （有待他决定的东西，做决定就在这一页）。因此不合并——把待决定的东西塞进只读页面，
 * 客户不会发现它在等自己。
 *
 * 接受是一次原子操作（服务端）：受理校验通过就当场成交，不通过则整条失败、建议**仍留在
 * 待你决定**，原因就地渲染。这里因此在失败时不刷新列表——刷新会把一条还没失败的建议
 * 说成别的状态，而它其实什么都没发生。
 *
 * 列表分页（ADR-0024）：一页里装着混合状态的建议，**四个分组按这一页的内容现分**
 * （空组不渲染）。分组与分页是同一份数据的两种切法，不是四份数据——各状态各拉一页
 * 的话，翻页会变成四次请求，而「这一页里有没有待决定的」这种问题也就没人答得上。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { PageHeader, PaginationBar, PanelCard } from "@wealth/shared";
import { formatDateTime } from "../advisory/timeliness";
import { useAdviceStore } from "../stores/advice";
import FailureNotice from "../trading/FailureNotice.vue";
import { describeAcceptanceFailure, type AcceptanceFailure } from "../trading/failure";
import {
  ADVICE_ACCEPTED,
  ADVICE_AWAITING,
  ADVICE_EXPIRED,
  ADVICE_REJECTED,
  DECISION_ACCEPT,
  DECISION_REJECT,
  type AdviceDecision,
  type AdviceStatus,
  type OperationAdvice,
} from "./types";

const store = useAdviceStore();
const router = useRouter();

const EMPTY_HINT =
  "还没有收到操作建议。你的客户经理为你发起、理财顾问放行之后，这里会出现待你决定的事。在那之前，你可以在「交易」里自己申购、赎回或转账。";

/** 正在提交的那一条：只有它显示按钮的 loading，别的行不受影响。 */
const decidingId = ref(0);

/** 失败挂在**那一条建议**上，而不是页面上：客户要一眼看出是哪条没成、为什么。 */
const failure = ref<{ adviceId: number; notice: AcceptanceFailure } | null>(null);

type AdviceGroup = {
  status: AdviceStatus;
  testid: string;
  /** 待决定的一组有接与拒两个动作；其余三组只回看。 */
  pending: boolean;
  items: OperationAdvice[];
};

// 四组同一套渲染：状态、锚点与「有没有动作」是这一组的全部差异（空组不渲染）。
const groups = computed<AdviceGroup[]>(() => {
  const all: AdviceGroup[] = [
    { status: ADVICE_AWAITING, testid: "advice-pending", pending: true, items: store.awaiting },
    { status: ADVICE_ACCEPTED, testid: "advice-accepted", pending: false, items: store.accepted },
    { status: ADVICE_REJECTED, testid: "advice-rejected", pending: false, items: store.rejected },
    { status: ADVICE_EXPIRED, testid: "advice-expired", pending: false, items: store.expired },
  ];
  return all.filter((group) => group.items.length > 0);
});

/** 「一条都没有」读的是**过滤后的总数**，不是本页条数（ADR-0024）。 */
const isEmpty = computed(() => store.loaded && !store.error && store.total === 0);

/**
 * 有内容但这一页恰好是空的（越界页）。
 *
 * 它不能说成「还没有收到建议」：那是一句关于整个人生的断言，而这里只是页码跑到了
 * 末页之后。两者分开，客户才知道该翻回去还是该去交易。
 */
const isBlankPage = computed(
  () => !store.loading && !store.error && store.total > 0 && groups.value.length === 0,
);

async function onDecide(item: OperationAdvice, decision: AdviceDecision): Promise<void> {
  failure.value = null;
  decidingId.value = item.id;
  try {
    await store.decide(item.id, decision);
  } catch (error) {
    failure.value = {
      adviceId: item.id,
      notice: describeAcceptanceFailure(
        error,
        decision === DECISION_ACCEPT ? "接受失败，请稍后重试" : "拒绝失败，请稍后重试",
      ),
    };
  } finally {
    decidingId.value = 0;
  }
}

function goTrading(): void {
  void router.push({ name: "trading" });
}

onMounted(() => {
  void store.refresh();
});
</script>

<template>
  <div class="advice">
    <PageHeader title="我的建议" :breadcrumb="['客户视图', '我的建议']" />

    <p v-if="store.loading && !store.loaded" class="advice__status">正在加载建议…</p>

    <p v-else-if="store.error" class="advice__error" role="alert" data-testid="advice-error">
      {{ store.error }}
    </p>

    <template v-else>
      <PanelCard v-for="group in groups" :key="group.status" :title="group.status">
        <ul class="advice__list" :data-testid="group.testid">
          <li
            v-for="item in group.items"
            :key="item.id"
            class="advice-item"
            :data-advice-id="item.id"
            data-testid="advice-item"
          >
            <p class="advice-item__product" data-testid="advice-product">
              {{ item.product_name ?? item.product_code }}（{{ item.product_code }}）
            </p>
            <p class="advice-item__action" data-testid="advice-action">
              {{ item.direction }} {{ item.amount }} 元
            </p>
            <p class="advice-item__reason" data-testid="advice-reason">{{ item.reason }}</p>

            <template v-if="group.pending">
              <p class="advice-item__meta" data-testid="advice-expires-at">
                有效期至 {{ formatDateTime(item.expires_at) }}，逾期未答即为已过期
              </p>
              <div class="advice-item__actions">
                <el-button
                  name="accept-advice"
                  :loading="decidingId === item.id"
                  @click="onDecide(item, DECISION_ACCEPT)"
                >
                  接受
                </el-button>
                <el-button
                  name="reject-advice"
                  :loading="decidingId === item.id"
                  @click="onDecide(item, DECISION_REJECT)"
                >
                  拒绝
                </el-button>
              </div>

              <div v-if="failure?.adviceId === item.id" data-testid="advice-failure">
                <FailureNotice :failure="failure.notice" />
              </div>
            </template>

            <p v-else class="advice-item__meta" data-testid="advice-decided-at">
              <template v-if="item.decided_at">
                {{ item.status }}于 {{ formatDateTime(item.decided_at) }}
              </template>
              <template v-else>
                送达于 {{ formatDateTime(item.released_at) }}，有效期内未作决定
              </template>
            </p>

            <p v-if="item.disclaimer" class="advice-item__disclaimer" data-testid="advice-disclaimer">
              {{ item.disclaimer }}
            </p>
          </li>
        </ul>
      </PanelCard>

      <PanelCard v-if="isBlankPage" title="这一页没有建议">
        <p class="advice__empty" data-testid="advice-page-empty">
          页码超出了范围，翻回前面几页看看。
        </p>
      </PanelCard>

      <PaginationBar
        v-if="store.total > 0"
        :total="store.total"
        :page="store.page"
        :page-size="store.pageSize"
        :disabled="store.loading"
        @update:page="store.goTo"
      />

      <PanelCard v-if="isEmpty" title="还没有收到建议">
        <p class="advice__empty" data-testid="advice-empty">{{ EMPTY_HINT }}</p>
        <el-button name="go-trading" data-testid="go-trading" @click="goTrading">去交易</el-button>
      </PanelCard>
    </template>
  </div>
</template>

<style scoped>
.advice {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.advice__list {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.advice-item {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  padding: var(--wm-space-3) var(--wm-space-4);
  /* 建议行的 1px 描边（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border-hairline);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-subtle);
}

.advice-item__product {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  font-weight: 600;
}

.advice-item__action {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
}

.advice-item__reason,
.advice-item__meta,
.advice-item__disclaimer {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.75;
}

.advice-item__actions {
  display: flex;
  gap: var(--wm-space-2);
  margin-top: var(--wm-space-2);
}

.advice__status,
.advice__empty {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.75;
}

.advice__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
