<script setup lang="ts">
import { computed } from "vue";
import { SectionCard } from "@wealth/shared";
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
  <SectionCard title="测评结果">
    <p data-testid="risk-level-label" class="level">{{ label }}</p>
    <p data-testid="risk-level-meaning">{{ meaning }}</p>
    <p class="validity">有效期至 {{ result.valid_until }}</p>
    <el-button name="retake" @click="emit('retake')">重新测评</el-button>
  </SectionCard>
</template>

<style scoped>
.level {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--wm-text-primary);
}

.validity {
  color: var(--wm-text-muted);
}
</style>
