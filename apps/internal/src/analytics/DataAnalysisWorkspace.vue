<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ApiError } from "@wealth/shared";
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
    <aside class="analytics-workspace__history">
      <h2>历史查询</h2>
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
    </aside>

    <div class="analytics-workspace__main">
      <el-card>
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
      </el-card>

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
  gap: 20px;
}

.analytics-workspace__history {
  background: white;
  padding: 16px;
  border-top: 3px solid #10263a;
  align-self: start;
}

.analytics-workspace__history h2 {
  margin: 0 0 12px;
  font-size: 12px;
  letter-spacing: 0.2em;
  color: #10263a;
}

.analytics-workspace__history-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: 100%;
  margin-bottom: 8px;
  padding: 8px;
  background: none;
  border: 0;
  border-left: 3px solid transparent;
  cursor: pointer;
  text-align: left;
}

.analytics-workspace__history-item:hover {
  border-left-color: #9a7b4f;
  background: #f3f6f8;
}

.analytics-workspace__history-item span {
  color: #909399;
  font-size: 12px;
}

.analytics-workspace__main {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.analytics-workspace__composer {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.analytics-workspace__examples {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.analytics-workspace__example {
  cursor: pointer;
  border: 1px solid #d3dce6;
  border-radius: 12px;
  background: #f4f4f5;
  padding: 2px 10px;
  font-size: 12px;
  color: #606266;
}

.analytics-workspace__example:hover {
  background: #e9e9eb;
}

.analytics-workspace__hint {
  color: #909399;
  font-size: 12px;
}

@media (max-width: 720px) {
  .analytics-workspace {
    grid-template-columns: 1fr;
  }
}
</style>
