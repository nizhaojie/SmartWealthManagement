<script setup lang="ts">
import { PanelCard } from "@wealth/shared";
import { formatDateTime, formatValue, gradeCaption } from "../format";
import { tagLabel } from "./profileView";
import type { ConflictRecord, RiskAssessmentRecord } from "./types";

// 历次风险评测与冲突记录：画像「怎么变成现在这样」的两条证据链。
defineProps<{
  assessments: RiskAssessmentRecord[];
  conflicts: ConflictRecord[];
}>();
</script>

<template>
  <PanelCard title="历次风险评测与冲突记录">
    <section class="block">
      <h4 class="block__title">历次风险评测</h4>
      <p v-if="!assessments.length" class="block__hint">还没有风险评测记录。</p>
      <ul v-else class="assessments" data-testid="assessment-history">
        <li v-for="item in assessments" :key="item.id" class="assessments__row">
          <span class="assessments__date">{{ item.assessment_date }}</span>
          <span class="assessments__grade">{{ gradeCaption(item.risk_level) }}</span>
          <span class="assessments__valid">有效至 {{ item.valid_until }}</span>
        </li>
      </ul>
    </section>

    <section class="block">
      <h4 class="block__title">冲突记录</h4>
      <p v-if="!conflicts.length" class="block__hint">没有冲突记录。</p>
      <ul v-else class="conflicts" data-testid="conflict-records">
        <li v-for="(record, index) in conflicts" :key="`${record.changed_at}-${index}`" class="conflicts__row">
          <span class="conflicts__time">{{ formatDateTime(record.changed_at) }}</span>
          <span class="conflicts__tag">{{ tagLabel(record.tag_key) }}</span>
          <span class="conflicts__change">
            {{ record.old_source }} 的「{{ formatValue(record.old_value) }}」被
            {{ record.new_source }} 改为「{{ formatValue(record.new_value) }}」
          </span>
        </li>
      </ul>
    </section>
  </PanelCard>
</template>

<style scoped>
.block + .block {
  margin-top: var(--wm-space-5);
}

.block__title {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-primary);
  font-size: 0.88rem;
  font-weight: 600;
}

.block__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.82rem;
}

.assessments,
.conflicts {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.assessments__row,
.conflicts__row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--wm-space-2);
  padding: var(--wm-space-2) var(--wm-space-3);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  font-size: 0.82rem;
}

.assessments__date,
.conflicts__time {
  color: var(--wm-text-muted);
  font-variant-numeric: tabular-nums;
}

.assessments__grade {
  color: var(--wm-text-primary);
  font-weight: 600;
}

.assessments__valid {
  color: var(--wm-text-muted);
}

.conflicts__tag {
  color: var(--wm-color-primary-strong);
  font-weight: 600;
}

.conflicts__change {
  color: var(--wm-text-primary);
  line-height: 1.6;
}
</style>
