<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { PageHeader, PanelCard } from "@wealth/shared";
import { errorMessage } from "../format";
import { useInspector } from "../shell/pageSlots";
import AnalyticsHistoryDetail from "./AnalyticsHistoryDetail.vue";
import AnalyticsHistoryPanel from "./AnalyticsHistoryPanel.vue";
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
const historyFailed = ref(false);
const examples = ref<AnalyticsExampleItem[]>([]);
const selectedHistoryId = ref<number | null>(null);

// 选中的那条记录：被新一轮历史刷掉时详情自然收起，不留一份孤立副本。
const selectedRecord = computed(
  () => history.value.find((entry) => entry.id === selectedHistoryId.value) ?? null,
);

async function loadHistory(): Promise<void> {
  try {
    history.value = await listAnalyticsHistory();
    historyFailed.value = false;
  } catch {
    // 历史拉不到不影响提问：留着已有的一份，只在栏里说明这一次没拉到。
    historyFailed.value = true;
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
    // 主区已经有新的结果了，先前点开的那条历史记录就该收起。
    selectedHistoryId.value = null;
    await loadHistory();
  } catch (error) {
    result.value = null;
    failureReason.value = errorMessage(error, "查询失败，请稍后重试");
  } finally {
    asking.value = false;
  }
}

/** 示例问题只是把问题写进输入框；历史条目不再这么用——点它是「查看这条记录」。 */
function reuseQuestion(value: string): void {
  question.value = value;
}

// 历史查询常驻壳层右侧栏：数据仍由这个页面拉取，栏只接收 props、上抛选中项。
useInspector(() => ({
  component: AnalyticsHistoryPanel,
  props: {
    history: history.value,
    selectedId: selectedHistoryId.value,
    failed: historyFailed.value,
    onSelect: (id: number) => {
      selectedHistoryId.value = id;
    },
  },
}));

onMounted(async () => {
  await Promise.all([loadHistory(), loadExamples()]);
});
</script>

<template>
  <div class="analytics">
    <PageHeader title="数据分析" :breadcrumb="['数据分析']" />

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

    <AnalyticsHistoryDetail v-if="selectedRecord" :record="selectedRecord" />

    <AnalyticsResultView v-if="result" :result="result" />
  </div>
</template>

<style scoped>
.analytics {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
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

.analytics__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
