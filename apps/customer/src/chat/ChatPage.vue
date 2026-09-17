<script setup lang="ts">
import { nextTick, reactive, ref } from "vue";
import { SectionCard } from "@wealth/shared";
import { streamChatMessage, type Citation } from "./api";

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  citations: Citation[];
  done: boolean;
};

type TextSegment = { type: "text"; value: string };
type CitationSegment = { type: "citation"; marker: string; citationIndex: number };

let nextId = 1;

const messages = reactive<ChatMessage[]>([]);
const draft = ref("");
const sending = ref(false);
const openCitationKey = ref<string | null>(null);
const listEl = ref<HTMLElement | null>(null);

function citationPanelId(messageId: number, citationIndex: number): string {
  return `citation-panel-${messageId}-${citationIndex}`;
}

function citationKey(messageId: number, citationIndex: number): string {
  return `${messageId}:${citationIndex}`;
}

function isCitationOpen(messageId: number, citationIndex: number): boolean {
  return openCitationKey.value === citationKey(messageId, citationIndex);
}

function toggleCitation(messageId: number, citationIndex: number): void {
  const key = citationKey(messageId, citationIndex);
  openCitationKey.value = openCitationKey.value === key ? null : key;
}

function renderSegments(text: string, citations: Citation[]): (TextSegment | CitationSegment)[] {
  if (citations.length === 0) {
    return [{ type: "text", value: text }];
  }

  const segments: (TextSegment | CitationSegment)[] = [];
  const pattern = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: text.slice(lastIndex, match.index) });
    }
    const marker = match[1];
    // marker 是后端 build_citations 原样保留的引用序号，按值精确匹配，
    // 不依赖角标在文本中出现的顺序与 citations 数组顺序一致。
    const citationIndex = citations.findIndex((citation) => citation.marker === Number(marker));
    if (citationIndex !== -1) {
      segments.push({ type: "citation", marker, citationIndex });
    } else {
      segments.push({ type: "text", value: match[0] });
    }
    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    segments.push({ type: "text", value: text.slice(lastIndex) });
  }

  return segments;
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

  messages.push({ id: nextId++, role: "user", text: question, citations: [], done: true });
  const assistantMessage: ChatMessage = {
    id: nextId++,
    role: "assistant",
    text: "",
    citations: [],
    done: false,
  };
  messages.push(assistantMessage);
  await scrollToBottom();

  await streamChatMessage(question, {
    onDelta(delta) {
      assistantMessage.text += delta;
      void scrollToBottom();
    },
    onDone(payload) {
      assistantMessage.text = payload.answer;
      assistantMessage.citations = payload.citations;
      assistantMessage.done = true;
      void scrollToBottom();
    },
    onError() {
      if (!assistantMessage.text) {
        assistantMessage.text = "对话连接已中断，请稍后重试，或拨打人工客服热线。";
      }
      assistantMessage.done = true;
      void scrollToBottom();
    },
  });

  sending.value = false;
}
</script>

<template>
  <SectionCard title="智能客服">
    <div ref="listEl" class="message-list">
      <div v-for="message in messages" :key="message.id" :class="['message', message.role]">
        <template v-if="message.role === 'assistant' && message.done">
          <span
            v-for="(segment, index) in renderSegments(message.text, message.citations)"
            :key="index"
          >
            <template v-if="segment.type === 'text'">{{ segment.value }}</template>
            <button
              v-else
              type="button"
              class="citation-badge"
              :aria-expanded="isCitationOpen(message.id, segment.citationIndex)"
              :aria-controls="citationPanelId(message.id, segment.citationIndex)"
              @click="toggleCitation(message.id, segment.citationIndex)"
            >{{ segment.marker }}</button>
          </span>
          <template v-for="(citation, citationIndex) in message.citations" :key="`panel-${citationIndex}`">
            <div
              v-if="isCitationOpen(message.id, citationIndex)"
              :id="citationPanelId(message.id, citationIndex)"
              class="citation-panel"
              role="dialog"
              :aria-label="`引用来源：${citation.title}`"
            >
              <p class="citation-panel-title">{{ citation.title }}</p>
              <p class="citation-panel-source">来源文件：{{ citation.source_file }}</p>
              <p v-if="citation.heading_path.length" class="citation-panel-heading">
                段落位置：{{ citation.heading_path.join(" / ") }}
              </p>
            </div>
          </template>
        </template>
        <template v-else>{{ message.text }}</template>
      </div>
    </div>
    <form class="chat-input" @submit.prevent="send">
      <el-input
        v-model="draft"
        name="chat-message"
        placeholder="向智能客服提问产品要素、政策条款或常见问题"
        :disabled="sending"
      />
      <el-button type="primary" native-type="submit" :loading="sending">发送</el-button>
    </form>
  </SectionCard>
</template>

<style scoped>
.message-list {
  max-height: 60vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.message.user {
  align-self: flex-end;
}

/* 引用角标是合规呈现面：必须保持可点、可定位，只做令牌化不做结构改动 */
.citation-badge {
  border: none;
  background: none;
  color: inherit;
  cursor: pointer;
  vertical-align: super;
  font-size: 0.75em;
  padding: 0 var(--wm-space-1);
}

.citation-panel {
  margin-top: var(--wm-space-2);
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 引用面板的 1px 边线（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border-hairline);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-page);
}

.citation-panel p {
  margin: 0;
}

.citation-panel-title {
  color: var(--wm-text-primary);
  font-weight: 600;
}

.citation-panel-source,
.citation-panel-heading {
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.chat-input {
  display: flex;
  gap: var(--wm-space-2);
  margin-top: var(--wm-space-3);
}
</style>
