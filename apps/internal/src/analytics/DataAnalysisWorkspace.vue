<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessageBox } from "element-plus";
import { ApiError, PageHeader, usePagination } from "@wealth/shared";
import { errorMessage } from "../format";
import { useInspector } from "../shell/pageSlots";
import AnalyticsHistoryDetail from "./AnalyticsHistoryDetail.vue";
import AnalyticsHistoryPanel from "./AnalyticsHistoryPanel.vue";
import ConversationThread from "./ConversationThread.vue";
import EmptyConversation from "./EmptyConversation.vue";
import MessageComposer from "./MessageComposer.vue";
import { listAnalyticsExamples, listAnalyticsHistory, runAnalyticsQuery } from "./api";
import { useAnalyticsThreadStore } from "./threadStore";
import type { AnalyticsExampleItem, AnalyticsHistoryItem } from "./types";

// 主区是一条**对话线程**（表单已消失）：提问与回答在 store 里累积，主区只负责呈现。
// 上一轮因此留在页面上，「追问」才在界面上成立——`session_id` 把它接到后端的短期记忆上。
const draft = ref("");
const examples = ref<AnalyticsExampleItem[]>([]);
const selectedHistoryId = ref<number | null>(null);

// 这一段页面生命周期里刚落地的轮次：只有它的解读逐字上屏。刷新或切模块回来时读到的是
// 一整条线程，那些轮次的解读直接是全文——20 轮一起重新逐字播放不是逐字感，是把页面拖住。
const typingRoundId = ref<string | null>(null);

const thread = useAnalyticsThreadStore();

/**
 * 在途 = 线程里还立着一颗没收尾的助手位。加载态从线程本身读，不另立一份会漂移的状态：
 * 「正在查询数据…」由那个助手位渲染，这里只管禁用提交。
 */
const asking = computed(() =>
  thread.messages.some((message) => message.role === "assistant" && message.status === "pending"),
);

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
    // 示例问题取不到不是故障：空态少几个可点的例子，问题照样问得出来。
    examples.value = [];
  }
}

/**
 * 发出一轮提问。入口有两个且只有两个：输入区的提交，与空态里点一条示例问题
 * （点了就发，不再只填进输入框）。两者都是「发出一条消息」，没有别的分支。
 */
async function ask(text: string): Promise<void> {
  const question = text.trim();
  // 空问题与「上一轮还在途」在这里再拦一道：输入区那一层的守卫是为了不吞掉已输入的字，
  // 而空态的示例问题不经过输入区，直接走到这里。
  if (!question || asking.value) return;

  // 这一轮先入线程（问题 + 「正在查询」的助手位）：失败也留在线程里，它不是没问过。
  const roundId = thread.beginRound(question);
  try {
    // 会话标识只在「清空对话」之后带：其余时候由登录凭证承载，同一次登录里的追问
    // 共用一个上下文（见 api.ts）。
    const response = await runAnalyticsQuery({
      question,
      sessionId: thread.sessionId ?? undefined,
    });
    thread.settleRound(roundId, response);
    typingRoundId.value = roundId;
    // 主区已经有新的结果了，先前点开的那条历史记录就该收起；这一轮的留痕是最新的一条，
    // 因此回到第一页取——停在原来的页上，刚问完的这一条不会出现。
    selectedHistoryId.value = null;
    await resetHistory();
  } catch (error) {
    // 业务码一并留下：五种失败各自成文案是呈现层的事（见 04），线程只负责别把它丢了。
    thread.failRound(roundId, {
      code: error instanceof ApiError ? error.code : null,
      message: errorMessage(error, "查询失败，请稍后重试"),
    });
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
}

// 历史查询常驻壳层右侧栏：数据仍由这个页面拉取，栏只接收 props、上抛选中项与翻页。
// 05 会把这件事搬进顶栏的抽屉，右栏随之塌成两栏。
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

    <!-- 历史查询的详情位：05 会把整件事搬进顶栏的抽屉，这里先留在对话面板上方。 -->
    <AnalyticsHistoryDetail v-if="selectedRecord" :record="selectedRecord" />

    <div class="analytics__panel">
      <EmptyConversation v-if="thread.isEmpty" :examples="examples" @ask="ask" />
      <ConversationThread
        v-else
        :messages="thread.messages"
        :dropped-rounds="thread.droppedRounds"
        :typing-id="typingRoundId ?? undefined"
      />

      <MessageComposer v-model="draft" :busy="asking" @submit="ask" />
    </div>
  </div>
</template>

<style scoped>
.analytics {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  /* 对话页是内容区的全部：占满可用高度，滚动交给消息区 */
  height: 100%;
  min-height: 0;
}

/* 对话面板：消息区 + 输入区同处一个面板内，铺满剩余高度。
   面板的 1px 描边是令牌纪律声明的极少数例外，由面板统一持有，消息区与输入区不再各自成卡。 */
.analytics__panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
  overflow: hidden;
}
</style>
