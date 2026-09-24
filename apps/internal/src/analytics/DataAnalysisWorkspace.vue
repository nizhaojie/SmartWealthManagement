<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessageBox } from "element-plus";
import { ApiError, PageHeader } from "@wealth/shared";
import { errorMessage } from "../format";
import AnalyticsHistoryDrawer from "./AnalyticsHistoryDrawer.vue";
import ConversationThread from "./ConversationThread.vue";
import EmptyConversation from "./EmptyConversation.vue";
import MessageComposer from "./MessageComposer.vue";
import { listAnalyticsExamples, runAnalyticsQuery } from "./api";
import { useAnalyticsThreadStore } from "./threadStore";
import type { AnalyticsExampleItem } from "./types";

// 主区是一条**对话线程**（表单已消失）：提问与回答在 store 里累积，主区只负责呈现。
// 上一轮因此留在页面上，「追问」才在界面上成立——`session_id` 把它接到后端的短期记忆上。
const draft = ref("");
const examples = ref<AnalyticsExampleItem[]>([]);

// 历史查询挂在抽屉里（05）：入口是页头那个按钮，抽屉自己取数取页。
const historyOpen = ref(false);

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

async function loadExamples(): Promise<void> {
  try {
    examples.value = await listAnalyticsExamples();
  } catch {
    // 示例问题取不到不是故障：空态少几个可点的例子，问题照样问得出来。
    examples.value = [];
  }
}

/**
 * 发出一轮提问。入口只有一个：输入区的提交（ticket 06 起，空态的示例问题只填进输入框，
 * 不再直接走到这里）。所以「发出」这件事在界面上总要过员工那一下回车。
 */
async function ask(text: string): Promise<void> {
  const question = text.trim();
  // 空问题与「上一轮还在途」在这里再拦一道：输入区那一层已经拦过，这里的守卫是给
  // 「同一帧里两次提交」这类漏网留的余量。
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
    // 这一轮的留痕不在这里刷新：抽屉每次打开都从第一页重取，问完再打开它自然是最新的。
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

// 历史查询的入口在**页头**、「清空对话」的右侧（ticket 06 从顶栏搬回来）：两个都是
// 「这一页的对话控制」，分居顶栏与页头不成组。它仍是个抽屉，不占第三栏——这一页不注入
// 检查器，AppShell 据此自动塌成两栏。

/** 把一句话送进输入框，**不自动发送**：「再问一次」与「试试这些」共用的那一半。 */
function fillDraft(question: string): void {
  draft.value = question;
}

/**
 * 「再问一次」把问题送回输入框，**不自动发送**。
 *
 * 它不是在原上下文里接着问：留痕那条记录当年所属的会话标识随那次登录结束，Redis 的记忆
 * 键（员工 + 会话标识）也就散了。所以这一下是「拿这句话在当前线程里重问一次」，问不问、
 * 要不要先改几个字，都由员工自己决定。
 */
function reuseQuestion(question: string): void {
  fillDraft(question);
  historyOpen.value = false;
}

onMounted(() => {
  void loadExamples();
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
        <el-button name="open-history" data-testid="open-history" @click="historyOpen = true">
          历史查询
        </el-button>
      </template>
    </PageHeader>

    <div class="analytics__panel">
      <!-- 示例问题只填进输入框，不替人发问：空态因此留在页面上（ticket 06）。 -->
      <EmptyConversation v-if="thread.isEmpty" :examples="examples" @pick="fillDraft" />
      <ConversationThread
        v-else
        :messages="thread.messages"
        :dropped-rounds="thread.droppedRounds"
        :typing-id="typingRoundId ?? undefined"
      />

      <MessageComposer v-model="draft" :busy="asking" @submit="ask" />
    </div>

    <!-- 抽屉挂在这里只是「由这一页提供」：它 append-to-body，位置与主区布局无关。
         开合走 v-model：人从抽屉那侧关掉（关闭按钮 / Esc / 点遮罩）时，这里也要跟上，
         否则页头那个入口会以为它还是开着的。 -->
    <AnalyticsHistoryDrawer v-model="historyOpen" @reuse="reuseQuestion" />
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
