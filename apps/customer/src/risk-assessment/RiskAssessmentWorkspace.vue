<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError, PageHeader, PanelCard } from "@wealth/shared";
import { getCurrentAssessment } from "./api";
import QuestionnairePage from "./QuestionnairePage.vue";
import ResultPage from "./ResultPage.vue";
import type { AssessmentResult } from "./types";

const result = ref<AssessmentResult | null>(null);
const retaking = ref(false);
const loading = ref(true);
const errorMessage = ref("");

async function load(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    result.value = await getCurrentAssessment();
    retaking.value = false;
  } catch (error) {
    // 404 是正常路径：这位客户还没做过测评，直接给问卷。
    // 其他失败才是异常，不能把接口故障伪装成「你还没测过」。
    if (error instanceof ApiError && error.code === 404) {
      result.value = null;
      retaking.value = true;
    } else {
      errorMessage.value = error instanceof ApiError ? error.message : "测评结果加载失败";
    }
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function onSubmitted(next: AssessmentResult): void {
  result.value = next;
  retaking.value = false;
}
</script>

<template>
  <div class="risk">
    <PageHeader title="风险测评" :breadcrumb="['客户视图', '风险测评']" />

    <p v-if="loading" class="risk__status">正在加载测评结果…</p>

    <PanelCard v-else-if="errorMessage" title="风险测评">
      <p class="risk__error" role="alert">{{ errorMessage }}</p>
      <el-button name="reload" @click="load">重新加载</el-button>
    </PanelCard>

    <ResultPage v-else-if="result && !retaking" :result="result" @retake="retaking = true" />

    <QuestionnairePage v-else @submitted="onSubmitted" />
  </div>
</template>

<style scoped>
.risk {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.risk__status {
  margin: 0;
  color: var(--wm-text-muted);
}

.risk__error {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-color-danger);
}
</style>
