<script setup lang="ts">
import { computed } from "vue";
import { PanelCard } from "@wealth/shared";
import { formatDateTime, gradeCaption } from "../format";
import CustomerGraphPanel from "../graph/CustomerGraphPanel.vue";
import AllocationComparisonChart from "./AllocationComparisonChart.vue";
import ProfileHistoryPanel from "./ProfileHistoryPanel.vue";
import ProfileTagsPanel from "./ProfileTagsPanel.vue";
import { profileWarnings, riskLevelOf, targetAllocationOf } from "./profileView";
import type { CustomerProfileView, Holding } from "./types";

// 画像主体：档案头、警示、熔断与评级、两张图，再把标签与历史交给下层两块。
// 它不直接调接口——数据由工作区拉好传进来，修正动作也往上抛。
const props = defineProps<{
  profile: CustomerProfileView;
  /**
   * 当前风险评测的有效期（资产接口给的结论，取的就是最近那次评测）。
   *
   * 警示的「是否过期」看它，而不是看历次评测里的第一条：评测历史分页之后，
   * `items[0]` 只是**当前这一页**的第一条，翻到第二页就不再是最近的那次评测了。
   */
  riskValidUntil: string | null;
  holdings: Holding[];
  loading?: boolean;
}>();

const emit = defineEmits<{
  correct: [payload: { tagKey: string; value: unknown; reason: string }];
}>();

const warnings = computed(() => profileWarnings(props.profile, props.riskValidUntil));

// 大字说的是**风险承受等级**（画像标签），不是四维度研判算出来的那个等级：研判的分数
// 与评测结论互为印证，两者不同是常态。把研判的等级当成承受等级挂在这里，顾问会按一个
// 系统并不执行的刻度去理解适当性（适当性按的是最近一次评测的结论）。
const riskLevel = computed(() => riskLevelOf(props.profile.tags));

const targetAllocation = computed(() => targetAllocationOf(props.profile.tags));
</script>

<template>
  <div class="profile-main">
    <PanelCard title="客户画像">
      <header class="head">
        <div>
          <p class="head__eyebrow">客户画像</p>
          <p class="head__name">{{ profile.real_name }}</p>
        </div>
        <span class="head__computed" data-testid="computed-at">
          计算于 {{ formatDateTime(profile.computed_at) }}
        </span>
      </header>

      <ul v-if="warnings.length" class="warnings" data-testid="profile-warning">
        <li v-for="warning in warnings" :key="warning">{{ warning }}</li>
      </ul>

      <div v-if="profile.judgement.circuit_break" class="circuit" data-testid="circuit-break">
        <span class="circuit__stamp">熔断</span>
        <div>
          <p class="circuit__title">硬性门槛已熔断</p>
          <ul class="circuit__reasons">
            <li v-for="reason in profile.judgement.reasons" :key="reason.code">
              {{ reason.message }}
            </li>
          </ul>
        </div>
      </div>

      <div v-else class="grade-block">
        <p class="grade__caption">风险承受等级</p>
        <p class="grade" data-testid="risk-grade">{{ gradeCaption(riskLevel) }}</p>
        <p
          v-if="profile.judgement.risk_level"
          class="grade__judgement"
          data-testid="judgement-grade"
        >
          四维度研判 {{ gradeCaption(profile.judgement.risk_level) }}
          <template v-if="profile.judgement.weighted_score !== null">
            （加权 {{ profile.judgement.weighted_score }}）
          </template>
        </p>
      </div>
    </PanelCard>

    <AllocationComparisonChart
      :target-allocation="targetAllocation"
      :holdings="holdings"
      :loading="loading"
    />

    <ProfileTagsPanel
      :tags="profile.tags"
      :dimension-scores="profile.judgement.dimension_scores"
      @correct="emit('correct', $event)"
    />

    <ProfileHistoryPanel
      :customer-id="profile.customer_id"
      :conflicts="profile.conflict_records"
    />

    <PanelCard title="持仓关系">
      <CustomerGraphPanel :customer-id="profile.customer_id" />
    </PanelCard>
  </div>
</template>

<style scoped>
.profile-main {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--wm-space-4);
}

.head__eyebrow {
  margin: 0 0 var(--wm-space-1);
  color: var(--wm-text-muted);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.head__name {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 1.15rem;
  font-weight: 700;
}

.head__computed {
  color: var(--wm-text-muted);
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
}

.warnings {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  margin: var(--wm-space-3) 0 0;
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 说明块左侧 3px 强调条（颜色走令牌） */
  border-left: 3px solid var(--wm-color-warning);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  color: var(--wm-color-warning);
  font-size: 0.82rem;
  line-height: 1.7;
  list-style: none;
}

.circuit {
  display: flex;
  align-items: center;
  gap: var(--wm-space-4);
  margin-top: var(--wm-space-4);
  padding: var(--wm-space-3) var(--wm-space-4);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-color-danger);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-subtle);
}

.circuit__stamp {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--wm-space-6);
  height: var(--wm-space-6);
  /* 印章边框：2px 是刻印观感的一部分，不是间距（令牌纪律声明的极少数例外，颜色仍走令牌） */
  border: 2px solid var(--wm-color-danger);
  border-radius: var(--wm-radius-sm);
  color: var(--wm-color-danger);
  font-size: 0.8rem;
  font-weight: 700;
}

.circuit__title {
  margin: 0 0 var(--wm-space-1);
  color: var(--wm-color-danger);
  font-size: 0.9rem;
  font-weight: 600;
}

.circuit__reasons {
  margin: 0;
  padding-left: var(--wm-space-4);
  color: var(--wm-text-primary);
  font-size: 0.82rem;
  line-height: 1.7;
}

.grade__caption {
  margin: var(--wm-space-4) 0 0;
  color: var(--wm-text-muted);
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.grade {
  margin: var(--wm-space-1) 0 0;
  color: var(--wm-text-primary);
  font-size: 1.6rem;
  font-weight: 700;
}

.grade__judgement {
  margin: var(--wm-space-2) 0 0;
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  line-height: 1.7;
  font-variant-numeric: tabular-nums;
}
</style>
