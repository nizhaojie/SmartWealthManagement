<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getCurrentAssessment } from "./api";
import QuestionnairePage from "./QuestionnairePage.vue";
import ResultPage from "./ResultPage.vue";
import type { AssessmentResult } from "./types";

const result = ref<AssessmentResult | null>(null);
const retaking = ref(false);
const loading = ref(true);

onMounted(async () => {
  try {
    result.value = await getCurrentAssessment();
  } catch {
    retaking.value = true;
  } finally {
    loading.value = false;
  }
});

function onSubmitted(next: AssessmentResult) {
  result.value = next;
  retaking.value = false;
}
</script>

<template>
  <p v-if="loading">正在加载评测结果…</p>
  <ResultPage v-else-if="result && !retaking" :result="result" @retake="retaking = true" />
  <QuestionnairePage v-else @submitted="onSubmitted" />
</template>
