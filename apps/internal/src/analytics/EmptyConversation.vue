<script setup lang="ts">
import type { AnalyticsExampleItem } from "./types";

// 空态：一句引导 + 示例问题。示例问题**点了就发问**，不再只填入输入框——
// 对话范式里那次「再按一次提问」是多余的（见 spec 的「对话壳与输入」一节）。
//
// 引导里写明可查范围：数据只能来自语义视图（已脱敏），超出范围的问法会被拒绝。
// 先说出来，「超出可查范围」才是可预期的结果，而不是碰了才知道。
defineProps<{ examples: AnalyticsExampleItem[] }>();
const emit = defineEmits<{ ask: [question: string] }>();
</script>

<template>
  <div class="empty" data-testid="conversation-empty">
    <p class="empty__guide">
      用一句自然语言说清你要看的数据，比如「上个月各风险等级的客户分布」。只能问语义视图覆盖的范围——客户、持仓、交易等已脱敏的指标；超出可查范围时我会直说查不到，不会去猜。
    </p>

    <div v-if="examples.length" class="empty__examples">
      <span class="empty__label">试试这些</span>
      <button
        v-for="example in examples"
        :key="example.question"
        type="button"
        class="empty__item"
        data-testid="example-question"
        @click="emit('ask', example.question)"
      >
        {{ example.question }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--wm-space-5) var(--wm-space-4);
}

.empty__guide {
  margin: 0;
  max-width: 60ch;
  color: var(--wm-text-muted);
  font-size: 0.88rem;
  line-height: 1.8;
}

.empty__examples {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wm-space-2);
}

.empty__label {
  color: var(--wm-text-muted);
  font-size: 0.78rem;
}

.empty__item {
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 示例问题是个可点的胶囊：1px 描边属令牌纪律声明的极少数例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-pill);
  background-color: var(--wm-bg-card);
  color: var(--wm-color-primary-strong);
  font-family: inherit;
  font-size: 0.82rem;
  cursor: pointer;
}

.empty__item:hover {
  border-color: var(--wm-color-primary);
  background-color: var(--wm-color-primary-soft);
}
</style>
