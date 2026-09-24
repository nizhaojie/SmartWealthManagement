<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessageBox } from "element-plus";
import { ApiError, PageHeader, PanelCard, usePagination } from "@wealth/shared";
import { errorMessage } from "../format";
import { useInspector } from "../shell/pageSlots";
import AnalyticsHistoryDetail from "./AnalyticsHistoryDetail.vue";
import AnalyticsHistoryPanel from "./AnalyticsHistoryPanel.vue";
import AnalyticsResultView from "./AnalyticsResultView.vue";
import { listAnalyticsExamples, listAnalyticsHistory, runAnalyticsQuery } from "./api";
import { useAnalyticsThreadStore } from "./threadStore";
import type { AnalyticsExampleItem, AnalyticsHistoryItem, AnalyticsQueryResponse } from "./types";

const question = ref("");
const asking = ref(false);
const result = ref<AnalyticsQueryResponse | null>(null);
const failureReason = ref("");

const examples = ref<AnalyticsExampleItem[]>([]);
const selectedHistoryId = ref<number | null>(null);

// 一轮问答不再是「一个被覆盖的结果」，而是一条可累积、活过刷新的线程（见 threadStore）。
const thread = useAnalyticsThreadStore();

// 历史查询是留痕表里的一页（ADR-0024）：只增的列表，靠 page/page_size 逐页取。
// 取数仍由这个页面做——栏只接收 props、上抛选中项与翻页，见下面的 useInspector。
const {
  items: history,
  total: historyTotal,
  page: historyPage,
  pageSize: historyPageSize,
  loading: historyLoading,
  errorMessage: historyError,
  goTo: goToHistoryPage,
  reset: resetHistory,
} = usePagination<AnalyticsHistoryItem>((query) => listAnalyticsHistory(query));

// 栏里只说一句「加载失败」：它是窄栏，放不下服务端的原文，也没必要重复。
const historyFailed = computed(() => historyError.value !== "");

// 选中的那条记录：翻页或新一轮历史把它带出这一页时，详情自然收起，不留一份孤立副本。
const selectedRecord = computed(
  () => history.value.find((entry) => entry.id === selectedHistoryId.value) ?? null,
);

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
  // 这一轮先入线程（问题 + 「正在查询」的助手位）：失败也留在线程里，它不是没问过。
  const roundId = thread.beginRound(question.value);
  asking.value = true;
  try {
    // 会话标识只在「清空对话」之后带：其余时候由登录凭证承载，同一次登录里的追问
    // 共用一个上下文（见 api.ts）。
    const response = await runAnalyticsQuery({
      question: question.value,
      sessionId: thread.sessionId ?? undefined,
    });
    result.value = response;
    thread.settleRound(roundId, response);
    // 主区已经有新的结果了，先前点开的那条历史记录就该收起；这一轮的留痕是最新的一条，
    // 因此回到第一页取——停在原来的页上，刚问完的这一条不会出现。
    selectedHistoryId.value = null;
    await resetHistory();
  } catch (error) {
    result.value = null;
    const reason = errorMessage(error, "查询失败，请稍后重试");
    failureReason.value = reason;
    // 业务码一并留下：五种失败各自成文案是呈现层的事（见 04），线程只负责别把它丢了。
    thread.failRound(roundId, {
      code: error instanceof ApiError ? error.code : null,
      message: reason,
    });
  } finally {
    asking.value = false;
  }
}

/** 会话里有内容时才要二次确认：空线程上这一下本来就没有上下文可丢。 */
const hasThread = computed(() => !thread.isEmpty);

/**
 * 清空对话 = 丢弃上下文，不是结束会话（唯一能结束会话的事仍是重新登录）。
 *
 * 清线程与 `sessionStorage`，并生成一个新标识随请求覆盖——后端 `session_id` 有值时
 * 优先于凭证，这一下就把上下文甩开了。**留痕一条不动**：那是逐次查询的合规记录，
 * 不受界面动作影响。
 */
async function clearThread(): Promise<void> {
  if (hasThread.value) {
    try {
      await ElMessageBox.confirm(
        "清空后主区回到空态，再提问不会带着清空前的上下文。历史查询的留痕不受影响。",
        "清空对话",
        { confirmButtonText: "清空", cancelButtonText: "取消", type: "warning" },
      );
    } catch {
      // 取消确认不是错误：什么都不做。
      return;
    }
  }
  thread.discardContext();
  result.value = null;
  failureReason.value = "";
}

/** 示例问题只是把问题写进输入框；历史条目不再这么用——点它是「查看这条记录」。 */
function reuseQuestion(value: string): void {
  question.value = value;
}

// 历史查询常驻壳层右侧栏：数据仍由这个页面拉取，栏只接收 props、上抛选中项与翻页。
useInspector(() => ({
  component: AnalyticsHistoryPanel,
  props: {
    history: history.value,
    selectedId: selectedHistoryId.value,
    failed: historyFailed.value,
    total: historyTotal.value,
    page: historyPage.value,
    pageSize: historyPageSize.value,
    loading: historyLoading.value,
    onSelect: (id: number) => {
      selectedHistoryId.value = id;
    },
    "onUpdate:page": (page: number) => {
      void goToHistoryPage(page);
    },
  },
}));

onMounted(async () => {
  await Promise.all([resetHistory(), loadExamples()]);
});
</script>

<template>
  <div class="analytics">
    <PageHeader title="数据分析" :breadcrumb="['数据分析']">
      <template #actions>
        <el-button
          name="clear-thread"
          data-testid="clear-thread"
          :disabled="!hasThread || asking"
          @click="clearThread"
        >
          清空对话
        </el-button>
      </template>
    </PageHeader>

    <PanelCard title="提问">
      <form class="ask" @submit.prevent="ask">
        <el-input
          v-model="question"
          name="question"
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

    <!-- 被线程上限裁掉的更早轮次不静默丢：留一句说明，让人知道线程不是从头开始的。 -->
    <p v-if="thread.droppedRounds" class="analytics__dropped" data-testid="dropped-rounds">
      更早的一轮已从本页移除
    </p>

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

.analytics__dropped {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}
</style>
