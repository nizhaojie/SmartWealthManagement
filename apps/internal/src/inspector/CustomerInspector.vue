<script setup lang="ts">
import { computed, ref, watch, type Ref } from "vue";
import { MeterBar, PanelCard, type Accent, type Paginated } from "@wealth/shared";
import {
  formatConfidence,
  formatDateTime,
  formatMoney,
  formatValue,
  gradeCaption,
  toPercent,
} from "../format";
import { listAllCustomers } from "../customers/api";
import type { CustomerListItem } from "../customers/types";
import { getCustomerAssets, getCustomerProfile } from "../profile/api";
import { riskLevelOf } from "../profile/profileView";
import type { CustomerAssets, CustomerProfileView, ProfileTag } from "../profile/types";
import { listAlerts } from "../risk/api";
import { levelTagType } from "../risk/riskView";
import type { AlertSummary } from "../risk/types";
import { useCurrentCustomerStore } from "../stores/currentCustomer";
import InspectorBlock from "./InspectorBlock.vue";
import type { InspectorLoadState } from "./types";

/**
 * 客户检查器：右侧常驻的「当前客户」上下文。看谁由全局「当前客户」决定。
 *
 * 四块内容各自独立拉取、各自独立 loading 与失败态：画像、资产、预警，
 * 外加一次 `GET /api/internal/customers` 只为拿客户分层——接口里没有单客户详情，
 * 而分层是客户卡要展示的字段之一。
 *
 * 预警那一路直接带上 `customer_id` 过滤并只取三条：列表分页之后，拉回来再在前端
 * 过滤只过滤得动当前页——「这位客户的预警」会变成「这位客户排在首页的那几条」，
 * 而卡片上仍然写着「共 N 条」。总数由服务端给的 `total` 说话。
 */
const store = useCurrentCustomerStore();
const customerId = computed(() => store.currentCustomerId);

// 卡片只列最近三条，就只要三条：多余的记录取回来也没地方放。
const ALERTS_SHOWN = 3;

const profile = ref<CustomerProfileView | null>(null);
const assets = ref<CustomerAssets | null>(null);
const alerts = ref<Paginated<AlertSummary> | null>(null);
const directory = ref<CustomerListItem[] | null>(null);

const profileState = ref<InspectorLoadState>("loading");
const assetsState = ref<InspectorLoadState>("loading");
const alertsState = ref<InspectorLoadState>("loading");
const directoryState = ref<InspectorLoadState>("loading");

// 换客户时旧请求可能后到，用请求令牌把过期响应丢掉。
let requestToken = 0;

async function loadBlock<T>(
  fetcher: () => Promise<T>,
  target: Ref<T | null>,
  state: Ref<InspectorLoadState>,
  token: number,
): Promise<void> {
  try {
    const value = await fetcher();
    if (token !== requestToken) return;
    target.value = value;
    state.value = "ready";
  } catch {
    if (token !== requestToken) return;
    target.value = null;
    state.value = "failed";
  }
}

function reset(): void {
  requestToken += 1;
  profile.value = null;
  assets.value = null;
  alerts.value = null;
  directory.value = null;
  profileState.value = "ready";
  assetsState.value = "ready";
  alertsState.value = "ready";
  directoryState.value = "ready";
}

function load(id: number): void {
  const token = ++requestToken;
  profile.value = null;
  assets.value = null;
  alerts.value = null;
  directory.value = null;
  profileState.value = "loading";
  assetsState.value = "loading";
  alertsState.value = "loading";
  directoryState.value = "loading";

  void loadBlock(() => getCustomerProfile(id), profile, profileState, token);
  void loadBlock(() => getCustomerAssets(id), assets, assetsState, token);
  void loadBlock(
    () =>
      listAlerts(
        { customerId: id },
        { page: 1, page_size: ALERTS_SHOWN },
      ),
    alerts,
    alertsState,
    token,
  );
  // 客户分层要从目录里查：目录按页给（ADR-0024），这里把页翻完再找那一位。
  void loadBlock(() => listAllCustomers(), directory, directoryState, token);
}

watch(
  customerId,
  (id) => {
    if (id === null) {
      reset();
      return;
    }
    load(id);
  },
  { immediate: true },
);

const customerLevel = computed(
  () => directory.value?.find((item) => item.id === customerId.value)?.customer_level ?? null,
);

const tags = computed<ProfileTag[]>(() => profile.value?.tags ?? []);

/** 等级大字说的是客户的**风险承受等级**，与画像主体的那一处同一个口径。 */
const riskLevel = computed(() => riskLevelOf(tags.value));
const warnings = computed(() => profile.value?.judgement.reasons.map((item) => item.message) ?? []);

/** 综合置信度：接口没有单一字段，取各标签置信度的均值——是聚合计出，不是编造。 */
const overallConfidence = computed(() => {
  if (!tags.value.length) return null;
  return tags.value.reduce((sum, tag) => sum + tag.confidence, 0) / tags.value.length;
});

// 整卡只在三路全部失败时才显示「暂不可用」：任何一路成功都能画出这张卡的一部分。
const cardState = computed<InspectorLoadState>(() => {
  const states = [profileState.value, assetsState.value, directoryState.value];
  if (states.every((state) => state === "failed")) return "failed";
  if (states.some((state) => state === "loading")) return "loading";
  return "ready";
});

// 条目与总数都由服务端给：这一页就是「这位客户最近的几条」，`total` 是他名下的
// 预警总数——两者不再需要（也无法）在前端对齐。
const customerAlerts = computed(() => (customerId.value === null ? [] : (alerts.value?.items ?? [])));
const customerAlertTotal = computed(() => (customerId.value === null ? 0 : (alerts.value?.total ?? 0)));

const holdings = computed(() => assets.value?.holdings ?? []);

function confidenceAccent(tag: ProfileTag): Accent {
  if (tag.expired) return "danger";
  if (tag.confidence >= 0.7) return "success";
  if (tag.confidence >= 0.4) return "primary";
  return "warning";
}
</script>

<template>
  <PanelCard title="当前客户">
    <template #actions>
      <button
        v-if="customerId !== null"
        type="button"
        class="inspector__clear"
        name="clear-customer"
        data-testid="clear-customer"
        @click="store.clear()"
      >
        清除
      </button>
    </template>

    <p v-if="customerId === null" class="inspector__hint" data-testid="inspector-empty">
      还没有选中客户。在客户画像、投顾助手、审核页或工单详情里选择一位客户，这里会常驻显示他的上下文。
    </p>

    <div v-else class="inspector__blocks">
      <InspectorBlock title="客户" :state="cardState">
        <dl class="facts">
          <div class="facts__row">
            <dt>姓名</dt>
            <dd data-testid="inspector-name">{{ profile?.real_name ?? "—" }}</dd>
          </div>
          <div class="facts__row">
            <dt>客户分层</dt>
            <dd data-testid="inspector-level">
              {{ customerLevel ?? (directoryState === "failed" ? "暂不可用" : "—") }}
            </dd>
          </div>
          <div class="facts__row">
            <dt>资产规模</dt>
            <dd data-testid="inspector-aum">
              {{ assets ? formatMoney(assets.total_market_value) : "—" }}
            </dd>
          </div>
          <div class="facts__row">
            <dt>持仓</dt>
            <dd>{{ assets ? `${assets.holding_count} 只` : "—" }}</dd>
          </div>
        </dl>
      </InspectorBlock>

      <InspectorBlock title="风险画像" :state="profileState">
        <template v-if="profile">
          <p class="grade__caption">风险承受等级</p>
          <p class="grade__level" data-testid="inspector-risk-level">
            {{ gradeCaption(riskLevel) }}
          </p>
          <p
            v-if="profile.judgement.risk_level"
            class="grade__judgement"
            data-testid="inspector-judgement"
          >
            四维度研判 {{ gradeCaption(profile.judgement.risk_level) }}
          </p>
          <p
            v-if="overallConfidence !== null"
            class="grade__confidence"
            data-testid="inspector-confidence"
          >
            综合置信度 {{ formatConfidence(overallConfidence) }}（各标签均值）
          </p>
          <ul v-if="warnings.length" class="grade__warnings" data-testid="inspector-warnings">
            <li v-for="warning in warnings" :key="warning">{{ warning }}</li>
          </ul>

          <div v-if="tags.length" class="dims">
            <div v-for="tag in tags" :key="tag.key" class="dims__row" :data-tag-key="tag.key">
              <MeterBar
                :label="tag.label"
                :percent="toPercent(tag.confidence)"
                :accent="confidenceAccent(tag)"
              />
              <p class="dims__value">
                {{ formatValue(tag.value) }}
                <span class="dims__source">{{ tag.source }}</span>
                <span v-if="tag.expired" class="dims__expired">已过期</span>
              </p>
            </div>
            <p class="inspector__note" data-testid="inspector-tags-note">
              维度条按接口实际返回的标签画；没有给的维度不画，也不补一个数值。
            </p>
          </div>
          <p v-else class="inspector__hint">还没有画像标签。</p>
        </template>
      </InspectorBlock>

      <InspectorBlock
        title="当前持仓"
        :state="assetsState"
        :empty="holdings.length === 0"
        empty-text="该客户当前没有持仓。"
      >
        <ul class="holdings" data-testid="inspector-holdings">
          <li
            v-for="holding in holdings.slice(0, 3)"
            :key="holding.product_code"
            class="holdings__row"
          >
            <span class="holdings__name">{{ holding.product_name }}</span>
            <b class="holdings__value">{{ formatMoney(holding.market_value) }}</b>
          </li>
        </ul>
        <p v-if="assets" class="inspector__total" data-testid="inspector-holdings-total">
          合计 {{ formatMoney(assets.total_market_value) }} · 共 {{ assets.holding_count }} 只
        </p>
      </InspectorBlock>

      <InspectorBlock
        title="风险预警"
        :state="alertsState"
        :empty="customerAlertTotal === 0"
        empty-text="该客户暂无预警记录。"
      >
        <ul class="alerts" data-testid="inspector-alerts">
          <li v-for="alert in customerAlerts" :key="alert.id" class="alerts__row">
            <span class="alerts__type">{{ alert.alert_type }}</span>
            <span :class="`alerts__level--${levelTagType(alert.alert_level)}`">
              {{ alert.alert_level }}
            </span>
            <span class="alerts__muted">{{ alert.status }}</span>
            <span class="alerts__muted">{{ formatDateTime(alert.created_at) }}</span>
          </li>
        </ul>
        <p class="inspector__total">共 {{ customerAlertTotal }} 条</p>
      </InspectorBlock>
    </div>
  </PanelCard>
</template>

<style scoped>
.inspector__blocks {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-5);
}

.inspector__hint,
.inspector__note,
.inspector__total {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.78rem;
  line-height: 1.7;
}

/* 装饰性说明走豁免档（--wm-text-placeholder 仅限 placeholder 与装饰） */
.inspector__note {
  margin-top: var(--wm-space-2);
  color: var(--wm-text-placeholder);
}

.inspector__clear {
  padding: var(--wm-space-1) var(--wm-space-2);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-card);
  color: var(--wm-text-muted);
  font-family: inherit;
  font-size: 0.75rem;
  cursor: pointer;
}

.inspector__clear:hover {
  color: var(--wm-text-primary);
}

.facts {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: 0;
}

.facts__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--wm-space-2);
}

.facts__row dt {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.facts__row dd {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}

.grade__caption {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.grade__level {
  margin: var(--wm-space-1) 0 0;
  color: var(--wm-text-primary);
  font-size: 1.3rem;
  font-weight: 700;
}

.grade__judgement {
  margin: var(--wm-space-1) 0 0;
  color: var(--wm-text-muted);
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
}

.grade__confidence {
  margin: var(--wm-space-1) 0 0;
  color: var(--wm-text-muted);
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
}

.grade__warnings {
  margin: var(--wm-space-2) 0 0;
  padding-left: var(--wm-space-4);
  color: var(--wm-color-warning);
  font-size: 0.78rem;
  line-height: 1.7;
}

.dims {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
  margin-top: var(--wm-space-3);
}

.dims__value {
  margin: var(--wm-space-1) 0 0;
  color: var(--wm-text-primary);
  font-size: 0.78rem;
  line-height: 1.6;
}

.dims__source {
  margin-left: var(--wm-space-2);
  color: var(--wm-text-muted);
}

.dims__expired {
  margin-left: var(--wm-space-2);
  color: var(--wm-color-danger);
}

.holdings,
.alerts {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.holdings__row,
.alerts__row {
  display: flex;
  align-items: baseline;
  gap: var(--wm-space-2);
  font-size: 0.8rem;
}

.holdings__name,
.alerts__type {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--wm-text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.holdings__value {
  color: var(--wm-text-primary);
  font-variant-numeric: tabular-nums;
}

.alerts__muted {
  color: var(--wm-text-muted);
  font-variant-numeric: tabular-nums;
}

.alerts__level--danger {
  color: var(--wm-color-danger);
}

.alerts__level--warning {
  color: var(--wm-color-warning);
}

.alerts__level--info {
  color: var(--wm-text-muted);
}
</style>
