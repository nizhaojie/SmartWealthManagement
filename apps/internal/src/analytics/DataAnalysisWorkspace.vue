<script setup lang="ts">
import { onMounted, ref } from "vue";
import { PageHeader, PanelCard } from "@wealth/shared";
import { errorMessage, formatDateTime } from "../format";
import AnalyticsResultView from "./AnalyticsResultView.vue";
import { listAnalyticsExamples, listAnalyticsHistory, runAnalyticsQuery } from "./api";
import type {
  AnalyticsExampleItem,
  AnalyticsHistoryItem,
  AnalyticsQueryResponse,
} from "./types";

// 页面级会话标识：同一页内的多轮追问共享它，刷新页面即新会话。
const sessionId = crypto.randomUUID();

const question = ref("");
const asking = ref(false);
const result = ref<AnalyticsQueryResponse | null>(null);
const failureReason = ref("");

const history = ref<AnalyticsHistoryItem[]>([]);
const examples = ref<AnalyticsExampleItem[]>([]);

async function loadHistory(): Promise<void> {
  try {
    history.value = await listAnalyticsHistory();
  } catch {
    // 历史拉不到不影响提问：留着已有的一份，不把整页变成错误态。
  }
}

async function loadExamples(): Promise<void> {
  try {
    examples.value = await listAnalyticsExamples();
  } catch {
    examples.value = [];
  }
}

async function ask(): Promise<void> {
  failureReason.value = "";
  if (!question.value.trim()) {
    failureReason.value = "请输入问题";
    return;
  }
  asking.value = true;
  try {
    result.value = await runAnalyticsQuery({ question: question.value, sessionId });
    await loadHistory();
  } catch (error) {
    result.value = null;
    failureReason.value = errorMessage(error, "查询失败，请稍后重试");
  } finally {
    asking.value = false;
  }
}

function reuseQuestion(value: string): void {
  question.value = value;
}

onMounted(async () => {
  await Promise.all([loadHistory(), loadExamples()]);
});
</script>

<template>
  <div class="analytics">
    <PageHeader title="数据分析" :breadcrumb="['数据分析']" />

    <div class="analytics__grid">
      <PanelCard title="历史查询">
        <ul v-if="history.length" class="history">
          <li v-for="entry in history" :key="entry.id">
            <button
              type="button"
              class="history__item"
              :data-testid="`history-item-${entry.id}`"
              @click="reuseQuestion(entry.question)"
            >
              <strong class="history__question">{{ entry.question }}</strong>
              <span class="history__meta">
                {{ entry.status }} · {{ formatDateTime(entry.create_time) }}
              </span>
            </button>
          </li>
        </ul>
        <p v-else class="analytics__empty">还没有历史查询</p>
      </PanelCard>

      <PanelCard title="提问">
        <form class="ask" @submit.prevent="ask">
          <el-input
            v-model="question"
            name="question"
            type="textarea"
            :rows="3"
            placeholder="用一句自然语言描述你要看的数据（Ctrl + Enter 提交）"
            @keydown.ctrl.enter="ask"
          />
          <div class="ask__row">
            <el-button
              type="primary"
              native-type="submit"
              name="ask"
              :loading="asking"
              data-testid="ask"
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
            data-testid="example-question"
            @click="reuseQuestion(example.question)"
          >
            {{ example.question }}
          </button>
        </div>

        <p v-if="failureReason" class="analytics__error" role="alert" data-testid="failure-reason">
          {{ failureReason }}
        </p>
      </PanelCard>
    </div>

    <AnalyticsResultView v-if="result" :result="result" />
  </div>
</template>

<style scoped>
.analytics {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.analytics__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  gap: var(--wm-space-4);
  align-items: start;
}

@media (max-width: 1280px) {
  .analytics__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.history {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: calc(var(--wm-space-6) * 12);
  overflow-y: auto;
}

.history__item {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  width: 100%;
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 细边框属令牌纪律声明的极少数 1px 例外；常态透明，只为 hover 时不让内容位移 */
  border: 1px solid transparent;
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.history__item:hover {
  border-color: var(--wm-color-primary);
}

.history__question {
  color: var(--wm-text-primary);
  font-size: 0.82rem;
  font-weight: 500;
  line-height: 1.6;
}

.history__meta {
  color: var(--wm-text-muted);
  font-size: 0.75rem;
}

.ask {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.ask__row {
  display: flex;
  justify-content: flex-end;
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

.analytics__empty {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.analytics__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
