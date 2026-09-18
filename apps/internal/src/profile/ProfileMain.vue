<script setup lang="ts">
import { computed } from "vue";
import { PanelCard } from "@wealth/shared";
import { formatDateTime, gradeCaption } from "../format";
import CustomerGraphPanel from "../graph/CustomerGraphPanel.vue";
import AllocationComparisonChart from "./AllocationComparisonChart.vue";
import ProfileHistoryPanel from "./ProfileHistoryPanel.vue";
import ProfileTagsPanel from "./ProfileTagsPanel.vue";
import { profileWarnings, targetAllocationOf } from "./profileView";
import type {
  CustomerProfileView,
  Holding,
  RiskAssessmentRecord,
} from "./types";

// 画像主体：档案头、警示、熔断与评级、两张图，再把标签与历史交给下层两块。
// 它不直接调接口——数据由工作区拉好传进来，修正动作也往上抛。
const props = defineProps<{
  profile: CustomerProfileView;
  assessments: RiskAssessmentRecord[];
  holdings: Holding[];
  loading?: boolean;
}>();

const emit = defineEmits<{
  correct: [payload: { tagKey: string; value: unknown; reason: string }];
}>();

const warnings = computed(() =>
  profileWarnings(props.profile, props.assessments[0]),
);

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

      <p v-else class="grade" data-testid="risk-grade">
        {{ gradeCaption(profile.judgement.risk_level) }}
      </p>
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
      :assessments="assessments"
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

.grade {
  margin: var(--wm-space-4) 0 0;
  color: var(--wm-text-primary);
  font-size: 1.6rem;
  font-weight: 700;
}
</style>
