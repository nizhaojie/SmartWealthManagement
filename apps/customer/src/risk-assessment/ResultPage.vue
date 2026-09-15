<script setup lang="ts">
import { computed } from "vue";
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
  <el-card>
    <h1>测评结果</h1>
    <p data-testid="risk-level-label">{{ label }}</p>
    <p data-testid="risk-level-meaning">{{ meaning }}</p>
    <p>有效期至 {{ result.valid_until }}</p>
    <el-button name="retake" @click="emit('retake')">重新测评</el-button>
  </el-card>
</template>
