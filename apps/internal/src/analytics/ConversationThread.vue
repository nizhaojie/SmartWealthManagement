<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import AssistantBubble from "./AssistantBubble.vue";
import UserBubble from "./UserBubble.vue";
import type { ThreadMessage } from "./threadStore";

// 消息列表：一轮问答是「用户气泡在上、助手气泡在下」，累积着不覆盖。
// 滚动只发生在这里（列表自己滚），底部输入区始终贴在面板下沿。
//
// `typingId` 是「哪一轮的解读正在逐字上屏」——只有刚到的轮次会逐字播，读回的历史轮次
// 直接是全文（见 `InterpretationText`），所以这个判断来自页面而不是这里。
const props = defineProps<{
  messages: ThreadMessage[];
  droppedRounds?: number;
  typingId?: string;
}>();

const listEl = ref<HTMLElement | null>(null);

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const el = listEl.value;
  if (el) {
    el.scrollTop = el.scrollHeight;
  }
}

// 新的一轮、收尾、失败都会换掉这个数组的引用（store 里是整体替换，不是就地改），
// 所以按引用监听就够——不必 deep，也不必在页面里手工再调一次滚动。
watch(() => props.messages, () => void scrollToBottom());

// 从别的模块切回本页时组件重新挂载：进来就落到底部，而不是停在最旧的一轮上。
onMounted(() => void scrollToBottom());
</script>

<template>
  <div ref="listEl" class="thread" data-testid="conversation-thread">
    <!-- 被线程上限裁掉的更早轮次不静默丢：留一句说明，让人知道线程不是从头开始的。 -->
    <p v-if="droppedRounds" class="thread__dropped" data-testid="dropped-rounds">
      更早的一轮已从本页移除
    </p>

    <template v-for="message in messages" :key="message.id">
      <UserBubble v-if="message.role === 'user'" :question="message.question" />
      <!-- 气泡里的内容长高了就把它带到底下：逐字上屏最新那几个字不该滑出可视区。 -->
      <AssistantBubble
        v-else
        :message="message"
        :typing="message.id === typingId"
        @grow="scrollToBottom"
      />
    </template>
  </div>
</template>

<style scoped>
.thread {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--wm-space-4);
}

.thread__dropped {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  text-align: center;
}
</style>
