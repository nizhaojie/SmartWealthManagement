<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { useChatStore, type ChatMessage } from "../stores/chat";
import CitationPanel from "./CitationPanel.vue";
import CiteChip from "./CiteChip.vue";
import { streamChatMessage } from "./api";
import { splitCitations } from "./citations";

// 断流时的兜底话术：客服链路的合规呈现面——客户必须始终有一条人工去路。
// 热线号与后端 human_service_channel 的取值一致；后端目前不把它暴露成接口，
// 改号时要两处一起改（回答文本里的号来自后端，不在这里）。
const CONNECTION_FALLBACK = "对话连接已中断，请稍后重试，或拨打人工客服热线 95588。";

const chat = useChatStore();

const draft = ref("");
const sending = ref(false);
const openCitationKey = ref<string | null>(null);
const listEl = ref<HTMLElement | null>(null);

const hasMessages = computed(() => chat.messages.length > 0);

function citationKey(messageId: number, citationIndex: number): string {
  return `${messageId}:${citationIndex}`;
}

function citationPanelId(messageId: number, citationIndex: number): string {
  return `citation-panel-${messageId}-${citationIndex}`;
}

function isCitationOpen(messageId: number, citationIndex: number): boolean {
  return openCitationKey.value === citationKey(messageId, citationIndex);
}

function toggleCitation(messageId: number, citationIndex: number): void {
  const key = citationKey(messageId, citationIndex);
  openCitationKey.value = openCitationKey.value === key ? null : key;
}

function segmentsOf(message: ChatMessage) {
  return splitCitations(message.text, message.citations);
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const el = listEl.value;
  if (el) {
    el.scrollTop = el.scrollHeight;
  }
}

async function send(): Promise<void> {
  const question = draft.value.trim();
  if (!question || sending.value) {
    return;
  }
  draft.value = "";
  sending.value = true;
  openCitationKey.value = null;

  const assistantId = chat.beginTurn(question);
  await scrollToBottom();

  await streamChatMessage(question, {
    onDelta(delta) {
      chat.appendDelta(assistantId, delta);
      void scrollToBottom();
    },
    onDone(payload) {
      chat.finishTurn(assistantId, payload);
      void scrollToBottom();
    },
    onError() {
      chat.failTurn(assistantId, CONNECTION_FALLBACK);
      void scrollToBottom();
    },
  });

  sending.value = false;
}
</script>

<template>
  <div class="chat">
    <header class="chat__head">
      <h2 class="chat__title">智能客服</h2>
      <p class="chat__hint">
        只回答有知识依据的问题：每条论断都挂来源角标；检索不到依据时我会直说，并给出人工渠道。
      </p>
    </header>

    <div ref="listEl" class="chat__list" data-testid="chat-list">
      <p v-if="!hasMessages" class="chat__empty" data-testid="chat-empty">
        可以问我产品要素、政策条款或常见问题，例如「这支产品的最短持有期是多久」。
      </p>

      <article
        v-for="message in chat.messages"
        :key="message.id"
        class="msg"
        :class="`msg--${message.role}`"
        :data-role="message.role"
      >
        <div class="msg__avatar" aria-hidden="true">{{ message.role === "user" ? "我" : "AI" }}</div>
        <div class="msg__bubble">
          <p v-if="message.role === 'assistant' && message.done" class="msg__text">
            <template v-for="(segment, index) in segmentsOf(message)" :key="index">
              <span v-if="segment.type === 'text'">{{ segment.value }}</span>
              <CiteChip
                v-else
                :marker="segment.marker"
                :open="isCitationOpen(message.id, segment.citationIndex)"
                :panel-id="citationPanelId(message.id, segment.citationIndex)"
                @toggle="toggleCitation(message.id, segment.citationIndex)"
              />
            </template>
          </p>
          <p v-else class="msg__text">{{ message.text }}</p>

          <template v-if="message.role === 'assistant' && message.done">
            <template v-for="(citation, index) in message.citations" :key="`panel-${index}`">
              <CitationPanel
                v-if="isCitationOpen(message.id, index)"
                :citation="citation"
                :panel-id="citationPanelId(message.id, index)"
              />
            </template>
          </template>
        </div>
      </article>
    </div>

    <form class="composer" @submit.prevent="send">
      <span class="composer__icon" aria-hidden="true">＋</span>
      <el-input
        v-model="draft"
        name="chat-message"
        class="composer__input"
        placeholder="继续追问，例如「最短持有期是多久」"
        :disabled="sending"
      />
      <el-button type="primary" native-type="submit" :loading="sending">发送</el-button>
    </form>
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.chat__head {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
}

.chat__title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--wm-text-primary);
}

.chat__hint {
  margin: 0;
  font-size: 0.85rem;
  color: var(--wm-text-muted);
}

/* 消息区自己滚：客户侧的对话是这一页的全部内容，composer 对齐 02 贴在下方 */
.chat__list {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  max-height: 58vh;
  overflow-y: auto;
  padding: var(--wm-space-4);
  /* 消息区的 1px 描边（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
}

.chat__empty {
  margin: 0;
  padding: var(--wm-space-5) 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  text-align: center;
}

.msg {
  display: flex;
  gap: var(--wm-space-3);
  max-width: 88%;
}

.msg--user {
  flex-direction: row-reverse;
  align-self: flex-end;
}

.msg__avatar {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--wm-space-6);
  height: var(--wm-space-6);
  border-radius: var(--wm-radius-pill);
  background-color: var(--wm-color-primary-tint);
  color: var(--wm-color-primary-strong);
  font-size: 0.75rem;
  font-weight: 700;
}

.msg__bubble {
  min-width: 0;
  padding: var(--wm-space-3) var(--wm-space-4);
  /* 气泡的 1px 描边（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-subtle);
  box-shadow: var(--wm-shadow-card);
}

.msg--user .msg__bubble {
  background-color: var(--wm-bg-user-bubble);
  border-color: transparent;
}

.msg__text {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  line-height: 1.75;
  /* 模型回答里的换行原样保留 */
  white-space: pre-wrap;
}

.composer {
  display: flex;
  align-items: center;
  gap: var(--wm-space-3);
  padding: var(--wm-space-3) var(--wm-space-4);
  /* composer 的 1px 描边（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
}

.composer__icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--wm-space-5);
  height: var(--wm-space-5);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  color: var(--wm-text-muted);
  font-size: 0.9rem;
}

.composer__input {
  flex: 1;
}

/* 02 的 composer 是一条无描边的输入带：去掉 EP 输入框自身的描边 */
.composer :deep(.el-input__wrapper) {
  box-shadow: none;
  background-color: transparent;
}
</style>
