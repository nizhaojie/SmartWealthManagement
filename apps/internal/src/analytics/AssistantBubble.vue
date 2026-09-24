<script setup lang="ts">
import InterpretationText from "./InterpretationText.vue";
import type { AssistantMessage } from "./threadStore";

// 助手气泡的外框：一轮的产物都装在这里。**占满主区宽度**——这页在重做时明确取消了限宽
// （宽表不该出横向滑动条），限宽气泡会把刚拆掉的那条滑动条请回来。
//
// 在途期间只给一个诚实的加载态：后端不告知阶段，编造「生成查询 → 校验 → 执行 → 解读」
// 会让员工把它当成信息。**不得**加阶段。
//
// 现在的三种形态：在途（正在查询数据…）/ 没问成（后端那句话原文）/ 已作答（解读）。
// 已作答这一支是 04 的落点：表格、可折叠 SQL、元信息行与警示都往这里长——它们长高时
// 同样要往上报一声 `grow`，线程才跟得上。
defineProps<{ message: AssistantMessage; typing?: boolean }>();
const emit = defineEmits<{ grow: [] }>();
</script>

<template>
  <article
    class="answer"
    data-role="assistant"
    data-testid="assistant-bubble"
    :data-status="message.status"
  >
    <p v-if="message.status === 'pending'" class="answer__loading" data-testid="loading">
      <span>正在查询数据…</span>
      <span class="answer__dots" aria-hidden="true">
        <i /><i /><i />
      </span>
    </p>

    <p
      v-else-if="message.status === 'failed'"
      class="answer__failure"
      role="alert"
      data-testid="failure-reason"
    >
      {{ message.failure?.message }}
    </p>

    <InterpretationText
      v-else-if="message.result"
      :text="message.result.interpretation"
      :typing="typing"
      @grow="emit('grow')"
    />
  </article>
</template>

<style scoped>
.answer {
  /* 满宽：不设 max-width，也不给 align-self，撑满消息列的整行 */
  padding: var(--wm-space-4);
  /* 气泡的 1px 描边（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border-hairline);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-card);
  box-shadow: var(--wm-shadow-card);
}

.answer__loading {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.9rem;
}

.answer__dots {
  display: inline-flex;
  gap: var(--wm-space-1);
}

.answer__dots i {
  width: var(--wm-space-1);
  height: var(--wm-space-1);
  border-radius: var(--wm-radius-pill);
  background-color: var(--wm-text-muted);
}

.answer__failure {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.9rem;
  line-height: 1.8;
}

@media (prefers-reduced-motion: no-preference) {
  .answer__dots i {
    animation: wbAnswerDot 1.2s var(--wm-ease-rise) infinite;
  }

  .answer__dots i:nth-child(2) {
    animation-delay: 0.15s;
  }

  .answer__dots i:nth-child(3) {
    animation-delay: 0.3s;
  }
}

@keyframes wbAnswerDot {
  0%,
  60%,
  100% {
    opacity: 0.35;
  }

  30% {
    opacity: 1;
  }
}
</style>
