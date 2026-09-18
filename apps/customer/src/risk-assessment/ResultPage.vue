<script setup lang="ts">
import { computed } from "vue";
import { PanelCard } from "@wealth/shared";
import { RISK_LEVEL_LABELS, RISK_LEVEL_MEANINGS } from "./grades";
import type { AssessmentResult } from "./types";

const props = defineProps<{
  result: AssessmentResult;
}>();

const emit = defineEmits<{
  retake: [];
}>();

const label = computed(() => RISK_LEVEL_LABELS[props.result.risk_level]);
const meaning = computed(() => RISK_LEVEL_MEANINGS[props.result.risk_level]);
</script>

<template>
  <PanelCard title="测评结果">
    <div class="result" data-testid="risk-result">
      <div class="result__grade">
        <b class="result__level" data-testid="risk-level">{{ result.risk_level }}</b>
        <span class="result__label" data-testid="risk-level-label">{{ label }}</span>
      </div>
      <p class="result__meaning" data-testid="risk-level-meaning">{{ meaning }}</p>
      <p class="result__validity">测评有效期至 {{ result.valid_until }}</p>
      <el-button name="retake" @click="emit('retake')">重新测评</el-button>
    </div>
  </PanelCard>
</template>

<style scoped>
.result {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--wm-space-3);
}

.result__grade {
  display: flex;
  align-items: baseline;
  gap: var(--wm-space-2);
}

.result__level {
  color: var(--wm-color-primary-strong);
  font-size: 2rem;
  font-weight: 700;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.result__label {
  color: var(--wm-text-primary);
  font-size: 1rem;
  font-weight: 600;
}

.result__meaning {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  line-height: 1.75;
}

.result__validity {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}
</style>
