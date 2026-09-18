<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listAlerts } from "../risk/api";

/**
 * 侧栏底部的「今日风险预警 N 条待处置」。
 *
 * 这是对 `GET /api/internal/risk-alerts?status=未处理` 的一次额外调用（外壳层），
 * 与风控监测页自己的列表调用互不共享缓存——这是可接受的代价，不为它引入全局查询缓存。
 * 三个角色都可见；数字天然按角色可见范围收窄（客户经理只看得到名下客户）。
 * N=0 给空态文案而不是隐藏卡片，加载失败给「暂不可用」。
 */
type LoadState = "loading" | "ready" | "failed";

const router = useRouter();
const state = ref<LoadState>("loading");
const pendingCount = ref(0);

async function load(): Promise<void> {
  state.value = "loading";
  try {
    pendingCount.value = (await listAlerts({ status: "未处理" })).length;
    state.value = "ready";
  } catch {
    state.value = "failed";
  }
}

function openAlerts(): void {
  void router.push("/risk-monitoring");
}

onMounted(load);
</script>

<template>
  <button
    type="button"
    class="risk-card"
    name="today-risk-alerts"
    data-testid="today-risk-alerts"
    @click="openAlerts"
  >
    <span class="risk-card__title">今日风险预警</span>
    <p v-if="state === 'loading'" class="risk-card__text">加载中…</p>
    <p
      v-else-if="state === 'failed'"
      class="risk-card__text"
      data-testid="today-risk-alerts-unavailable"
    >
      暂不可用
    </p>
    <p
      v-else-if="pendingCount === 0"
      class="risk-card__text"
      data-testid="today-risk-alerts-empty"
    >
      今日没有待处置的预警
    </p>
    <p v-else class="risk-card__text">
      <b class="risk-card__count" data-testid="today-risk-alerts-count">{{ pendingCount }}</b>
      条待处置
    </p>
  </button>
</template>

<style scoped>
.risk-card {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  width: 100%;
  padding: var(--wm-space-3);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-subtle);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.risk-card:hover {
  border-color: var(--wm-color-danger);
}

.risk-card__title {
  color: var(--wm-text-muted);
  font-size: 0.75rem;
  font-weight: 600;
}

.risk-card__text {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  line-height: 1.5;
}

.risk-card__count {
  color: var(--wm-color-danger);
  font-size: 1.15rem;
  font-variant-numeric: tabular-nums;
}

@media (prefers-reduced-motion: no-preference) {
  .risk-card__count {
    animation: wbPulse 2.4s ease-in-out infinite;
  }
}
</style>
