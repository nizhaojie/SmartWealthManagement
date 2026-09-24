<script setup lang="ts">
import { computed, ref, watch } from "vue";
import AssistantResult from "./AssistantResult.vue";
import InterpretationText from "./InterpretationText.vue";
import { failureNotice } from "./failureCopy";
import type { AssistantMessage } from "./threadStore";

// 助手气泡的外框：一轮的产物都装在这里。**占满主区宽度**——这页在重做时明确取消了限宽
// （宽表不该出横向滑动条），限宽气泡会把刚拆掉的那条滑动条请回来。
//
// 在途期间只给一个诚实的加载态：后端不告知阶段，编造「生成查询 → 校验 → 执行 → 解读」
// 会让员工把它当成信息。**不得**加阶段。
//
// 三种形态：在途（正在查询数据…）/ 没问成（业务码各自的警示块）/ 已作答（解读 + 结果面）。
const props = defineProps<{ message: AssistantMessage; typing?: boolean }>();
const emit = defineEmits<{ grow: [] }>();

/** 没问成时呈现什么：文案由业务码决定，后端原文另起一行留着诊断（见 `failureCopy`）。 */
const notice = computed(() =>
  props.message.failure ? failureNotice(props.message.failure) : null,
);

// 结果面（表格 / SQL / 元信息）**等解读播完再出现**：整包是一起到的，让它们同时铺开，
// 逐字感就只剩一半——上面在打字，下面已经成型。
// `typing` 为假的轮次（读回的、以及被下一轮顶下去的）解读本来就是全文直出，结果面没有等的理由。
const revealed = ref(!props.typing);
watch(
  () => props.typing,
  (typing) => {
    revealed.value = !typing;
  },
);

// 结果面出现会把气泡撑高：报一声，线程才把这一下带进可视区（与解读逐字上屏同一套）。
watch(revealed, (value) => {
  if (value) emit("grow");
});
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

    <!-- 被拒绝的查询看到的是一句说清原因的警示，不是一张空表格。
         这一块不用 el-alert：受合规约束的呈现面只吃样式、不吃语义——结构与 role="alert"
         由我们自己持有（ADR-0009），Element Plus 只提供主题令牌。 -->
    <template v-else-if="message.status === 'failed'">
      <p class="answer__failure" role="alert" data-testid="failure-reason">
        {{ notice?.headline }}
      </p>
      <p v-if="notice?.detail" class="answer__detail" data-testid="failure-detail">
        后端原文：{{ notice.detail }}
      </p>
    </template>

    <template v-else-if="message.result">
      <InterpretationText
        :text="message.result.interpretation"
        :typing="typing"
        @grow="emit('grow')"
        @done="revealed = true"
      />
      <AssistantResult v-if="revealed" :result="message.result" @grow="emit('grow')" />
    </template>
  </article>
</template>

<style scoped>
.answer {
  /* 满宽：不设 max-width，也不给 align-self，撑满消息列的整行 */
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
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

/* 警示块：文案由业务码决定，底色与文字色都来自令牌 */
.answer__failure {
  margin: 0;
  padding: var(--wm-space-3) var(--wm-space-4);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-subtle);
  color: var(--wm-color-danger);
  font-size: 0.9rem;
  line-height: 1.8;
}

/* 后端原文是诊断线索，不是第二句错误：压小、压低，不与上面的文案争注意力 */
.answer__detail {
  margin: 0;
  color: var(--wm-text-placeholder);
  font-size: 0.78rem;
  line-height: 1.7;
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
