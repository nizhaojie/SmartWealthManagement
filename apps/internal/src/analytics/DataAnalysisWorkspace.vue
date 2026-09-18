<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError, PanelCard } from "@wealth/shared";
import { listAnalyticsExamples, listAnalyticsHistory, runAnalyticsQuery } from "./api";
import AnalyticsResultView from "./AnalyticsResultView.vue";
import type {
  AnalyticsExampleItem,
  AnalyticsHistoryItem,
  AnalyticsQueryResponse,
} from "./types";

// 追问上下文标识：同一次打开的工作台内，追问共享上下文（上一轮问题进入
// 生成上下文）；重新打开页面即重新开始。它只圈定追问上下文，不是
// CONTEXT.md 意义上跨整个登录期的「会话」。
const sessionId = crypto.randomUUID();

const question = ref("");
const asking = ref(false);
const result = ref<AnalyticsQueryResponse | null>(null);
// 答不上来时的原因说明（超出可查范围 / 无法生成查询），渲染原因而非空表格。
const failureReason = ref("");

const history = ref<AnalyticsHistoryItem[]>([]);
const examples = ref<AnalyticsExampleItem[]>([]);

async function ask() {
  const text = question.value.trim();
  if (!text || asking.value) {
    return;
  }
  asking.value = true;
  failureReason.value = "";
  try {
    result.value = await runAnalyticsQuery({ question: text, sessionId });
    // 新的一次查询已留痕，刷新历史让它立即可重用。
    history.value = await listAnalyticsHistory();
  } catch (error) {
    result.value = null;
    failureReason.value =
      error instanceof ApiError ? error.message : "查询失败，请稍后重试";
  } finally {
    asking.value = false;
  }
}

function reuseQuestion(text: string) {
  question.value = text;
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

onMounted(async () => {
  try {
    [history.value, examples.value] = await Promise.all([
      listAnalyticsHistory(),
      listAnalyticsExamples(),
    ]);
  } catch {
    // 历史与示例加载失败不阻塞提问主流程。
  }
});
</script>

<template>
  <div class="analytics-workspace">
    <PanelCard title="历史查询" class="analytics-workspace__history">
      <button
        v-for="entry in history"
        :key="entry.id"
        type="button"
        :data-test="`history-item-${entry.id}`"
        class="analytics-workspace__history-item"
        @click="reuseQuestion(entry.question)"
      >
        <strong>{{ entry.question }}</strong>
        <span>{{ entry.status }} · {{ formatDateTime(entry.create_time) }}</span>
      </button>
      <p v-if="!history.length" class="analytics-workspace__hint">还没有历史查询</p>
    </PanelCard>

    <div class="analytics-workspace__main">
      <PanelCard title="提问">
        <div class="analytics-workspace__composer">
          <el-input
            v-model="question"
            type="textarea"
            :rows="2"
            name="question"
            placeholder="用日常语言提出数据问题，例如：各产品类型的持仓市值分布"
            @keydown.ctrl.enter="ask"
          />
          <el-button
            type="primary"
            :loading="asking"
            data-test="ask"
            @click="ask"
          >
            {{ asking ? "正在查询…" : "提问" }}
          </el-button>
        </div>
        <div v-if="examples.length" class="analytics-workspace__examples">
          <span class="analytics-workspace__hint">试试这样问：</span>
          <button
            v-for="example in examples"
            :key="example.question"
            type="button"
            class="analytics-workspace__example"
            data-test="example-question"
            @click="reuseQuestion(example.question)"
          >
            {{ example.question }}
          </button>
        </div>
      </PanelCard>

      <el-alert
        v-if="failureReason"
        type="info"
        :closable="false"
        data-test="failure-reason"
        :title="failureReason"
      />

      <AnalyticsResultView v-if="result" :result="result" />
    </div>
  </div>
</template>

<style scoped>
.analytics-workspace {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: var(--wm-space-5);
}

.analytics-workspace__history {
  align-self: start;
}

.analytics-workspace__history-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
  margin-bottom: var(--wm-space-2);
  padding: var(--wm-space-2);
  background: none;
  border: 0;
  /* 3px 左指示条：悬停态标记，与 StatCard 左条同规格（非 1px 细线例外） */
  border-left: 3px solid transparent;
  cursor: pointer;
  text-align: left;
  color: var(--wm-text-primary);
}

.analytics-workspace__history-item:hover {
  border-left-color: var(--wm-color-primary);
  background: var(--wm-bg-page);
}

.analytics-workspace__history-item span {
  color: var(--wm-text-muted);
  font-size: 12px;
}

.analytics-workspace__main {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.analytics-workspace__composer {
  display: flex;
  gap: var(--wm-space-3);
  align-items: flex-start;
}

.analytics-workspace__examples {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
  flex-wrap: wrap;
  margin-top: var(--wm-space-3);
}

.analytics-workspace__example {
  cursor: pointer;
  /* 示例问题做成药丸按钮：1px 边线（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-lg);
  background: var(--wm-bg-page);
  padding: var(--wm-space-1) var(--wm-space-3);
  font-size: 12px;
  color: var(--wm-text-secondary);
}

.analytics-workspace__example:hover {
  /* 中性面没有比 bg-page 深一档的专用令牌，以边框令牌作最深的悬停底色（不引入新色值） */
  background: var(--wm-border);
  color: var(--wm-text-primary);
}

.analytics-workspace__hint {
  color: var(--wm-text-muted);
  font-size: 12px;
}

@media (max-width: 720px) {
  .analytics-workspace {
    grid-template-columns: 1fr;
  }
}
</style>
