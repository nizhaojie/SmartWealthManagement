<script setup lang="ts">
import { onMounted, ref } from "vue";
import { PanelCard } from "@wealth/shared";
import AnalyticsResultView from "../analytics/AnalyticsResultView.vue";
import type { AnalyticsQueryResponse } from "../analytics/types";
import { errorMessage } from "../format";
import { askRiskQuestion, listRiskQueryExamples } from "./api";
import type { TabSummary } from "./riskView";
import { useTabSummary } from "./useTabSummary";

// 风控问答与数据分析是同一条受限查询链路上的两份 Agent 配置，
// 会话标识固定在这一页，刷新即新会话。
const emit = defineEmits<{ summary: [value: TabSummary] }>();

const sessionId = crypto.randomUUID();

const question = ref("");
const asking = ref(false);
const result = ref<AnalyticsQueryResponse | null>(null);
const queryFailure = ref("");
const examples = ref<{ question: string }[]>([]);

async function ask(): Promise<void> {
  queryFailure.value = "";
  if (!question.value.trim()) {
    queryFailure.value = "请输入问题";
    return;
  }
  asking.value = true;
  try {
    result.value = await askRiskQuestion({ question: question.value, sessionId });
  } catch (error) {
    result.value = null;
    queryFailure.value = errorMessage(error, "查询失败，请稍后重试");
  } finally {
    asking.value = false;
  }
}

async function loadExamples(): Promise<void> {
  try {
    examples.value = await listRiskQueryExamples();
  } catch {
    examples.value = [];
  }
}

onMounted(loadExamples);

useTabSummary(
  (value) => emit("summary", value),
  () => ({
    headline: result.value ? `已提问：${result.value.question}` : "尚未提问",
    count: result.value ? result.value.row_count : null,
  }),
);
</script>

<template>
  <div class="query">
    <PanelCard title="提问">
      <form class="query__form" @submit.prevent="ask">
        <el-input
          v-model="question"
          name="risk-question"
          placeholder="用一句自然语言描述要看的风险数据（回车提交）"
        />
        <div class="query__row">
          <el-button
            type="primary"
            native-type="submit"
            name="ask-risk-query"
            data-testid="ask-risk-query"
            :loading="asking"
          >
            提问
          </el-button>
        </div>
      </form>

      <div v-if="examples.length" class="examples">
        <span class="examples__label">示例问题</span>
        <button
          v-for="example in examples"
          :key="example.question"
          type="button"
          class="examples__item"
          data-testid="risk-query-example"
          @click="question = example.question"
        >
          {{ example.question }}
        </button>
      </div>

      <el-alert
        v-if="queryFailure"
        class="query__failure"
        type="error"
        :closable="false"
        :title="queryFailure"
        data-testid="risk-query-failure"
      />
    </PanelCard>

    <AnalyticsResultView v-if="result" :result="result" />
  </div>
</template>

<style scoped>
.query {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.query__form {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.query__row {
  display: flex;
  justify-content: flex-end;
}

.query__failure {
  margin-top: var(--wm-space-3);
}

.examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wm-space-2);
  margin-top: var(--wm-space-3);
}

.examples__label {
  color: var(--wm-text-muted);
  font-size: 0.78rem;
}

.examples__item {
  padding: var(--wm-space-1) var(--wm-space-2);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-pill);
  background-color: var(--wm-bg-card);
  color: var(--wm-color-primary-strong);
  font-family: inherit;
  font-size: 0.78rem;
  cursor: pointer;
}

.examples__item:hover {
  border-color: var(--wm-color-primary);
}
</style>
