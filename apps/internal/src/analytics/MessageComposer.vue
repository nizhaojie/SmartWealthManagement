<script setup lang="ts">
import { nextTick, ref } from "vue";
import type { InputInstance } from "element-plus";

// 底部输入区：多行自适应（2–4 行），**Ctrl+Enter 提交、Enter 换行**。
// Enter 留给换行是双向的收益：中文输入法组字时的 Enter 上屏天然不会被当成发送。
//
// 提交之后清空并留在输入框里（接着问下一句），清空与聚焦都在这里做完——
// 页面只管把问题送出去，不用记住输入框的状态。
const text = defineModel<string>({ required: true });
const props = defineProps<{ busy?: boolean }>();
const emit = defineEmits<{ submit: [question: string] }>();

const inputRef = ref<InputInstance | null>(null);

function focus(): void {
  inputRef.value?.focus();
}

async function submit(): Promise<void> {
  const question = text.value.trim();
  // 上一轮还在途时不接这一下：输入框里的字原样留着，不静默吞掉。
  if (!question || props.busy) return;
  text.value = "";
  emit("submit", question);
  await nextTick();
  focus();
}

defineExpose({ focus });
</script>

<template>
  <form class="ask" @submit.prevent="submit">
    <el-input
      ref="inputRef"
      v-model="text"
      name="question"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 4 }"
      placeholder="用一句自然语言描述你要看的数据（Ctrl + Enter 发送）"
      @keydown.ctrl.enter.prevent="submit"
    />

    <div class="ask__row">
      <span class="ask__hint">Ctrl + Enter 发送，Enter 换行</span>
      <el-button
        type="primary"
        native-type="submit"
        name="ask"
        data-testid="ask"
        :loading="busy"
      >
        发送
      </el-button>
    </div>
  </form>
</template>

<style scoped>
.ask {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  flex-shrink: 0;
  padding: var(--wm-space-3) var(--wm-space-4);
  /* 输入带用实线顶部分隔，与上方消息区拉开区分度（细线属令牌纪律声明的极少数例外） */
  border-top: 1px solid var(--wm-border-hairline);
  background-color: var(--wm-bg-subtle);
}

.ask__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--wm-space-3);
}

.ask__hint {
  color: var(--wm-text-muted);
  font-size: 0.75rem;
}
</style>
