<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { Warning } from "@element-plus/icons-vue";
import { listAlerts } from "../risk/api";
import { useLayoutStore } from "../stores/layout";

/**
 * 侧栏底部的「今日风险预警 N 条待处置」。
 *
 * 这是对 `GET /api/internal/risk-alerts?status=未处理` 的一次额外调用（外壳层），
 * 与风控监测页自己的列表调用互不共享缓存——这是可接受的代价，不为它引入全局查询缓存。
 * 三个角色都可见；数字天然按角色可见范围收窄（客户经理只看得到名下客户）。
 * N=0 给空态文案而不是隐藏卡片，加载失败给「暂不可用」。
 *
 * 侧栏折叠成图标条时，这里渲染图标 + 角标（待处置数）：N=0 不显示角标、失败态仅图标，
 * 与展开态的空态/失败语义对齐，只是折叠下不显示文字。数据来源不变（listAlerts）。
 */
type LoadState = "loading" | "ready" | "failed";

const router = useRouter();
const layout = useLayoutStore();
const state = ref<LoadState>("loading");
const pendingCount = ref(0);

const collapsed = computed(() => layout.sidebarCollapsed);

async function load(): Promise<void> {
  state.value = "loading";
  try {
    // 只要「有多少条待处置」这一个数字，所以只取一条、读它的 `total`：列表接口的
    // 总数是过滤后的总数（ADR-0024），拿 `items.length` 数出来的只是第一页。
    const page = await listAlerts({ status: "未处理" }, { page: 1, page_size: 1 });
    pendingCount.value = page.total;
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
    :class="{ 'risk-card--collapsed': collapsed }"
    name="today-risk-alerts"
    data-testid="today-risk-alerts"
    :aria-label="collapsed ? '今日风险预警' : undefined"
    @click="openAlerts"
  >
    <!-- 折叠态：图标 + 角标。角标只在成功取到且 N>0 时出现；失败态仅图标。 -->
    <template v-if="collapsed">
      <span class="risk-card__icon-wrap" data-testid="today-risk-alerts-icon">
        <Warning class="risk-card__icon" aria-hidden="true" />
        <span
          v-if="state === 'ready' && pendingCount > 0"
          class="risk-card__badge"
          data-testid="today-risk-alerts-count"
        >
          {{ pendingCount }}
        </span>
      </span>
    </template>
    <!-- 展开态：原有标题 + 状态文案 -->
    <template v-else>
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
    </template>
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

/* 折叠态：图标条里的小卡只剩一个居中图标（+ 可选角标），去掉纵向文字堆叠 */
.risk-card--collapsed {
  align-items: center;
  justify-content: center;
  padding: var(--wm-space-2);
}

.risk-card__icon-wrap {
  position: relative;
  display: inline-flex;
}

.risk-card__icon {
  width: var(--wm-space-5);
  height: var(--wm-space-5);
  color: var(--wm-color-danger);
}

/* 角标锚在图标右上角，与导航徽标同手法：danger 淡底 + danger 文字，不写死底色 */
.risk-card__badge {
  position: absolute;
  top: -6px;
  right: -10px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: var(--wm-radius-pill);
  background-color: color-mix(in srgb, var(--wm-color-danger) 12%, transparent);
  color: var(--wm-color-danger);
  font-size: 0.65rem;
  font-weight: 700;
  line-height: 16px;
  text-align: center;
  font-variant-numeric: tabular-nums;
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
