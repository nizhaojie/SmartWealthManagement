<script setup lang="ts">
import { nextTick, ref } from "vue";
import { EditPen } from "@element-plus/icons-vue";
import type { InputInstance } from "element-plus";

// 底部输入区：**单行**输入，与客服侧的对话输入同一形态——左侧一个图标底座、中间输入、右侧发送。
// 回车即提交，走的是表单的原生隐式提交（不挂 keydown）：「没有换行」是单行 input 的形态决定的，
// 不是靠拦键盘；中文输入法组字时的回车由输入法自己吃掉，也就不会把半句送出去。
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
  // 上一轮还在途时不接这一下（页面那一层也拦一道）：输入框里的字原样留着，不静默吞掉。
  if (!question || props.busy) return;
  text.value = "";
  emit("submit", question);
  await nextTick();
  focus();
}
</script>

<template>
  <form class="ask" @submit.prevent="submit">
    <span class="ask__icon" aria-hidden="true">
      <el-icon><EditPen /></el-icon>
    </span>

    <el-input
      ref="inputRef"
      v-model="text"
      name="question"
      class="ask__input"
      placeholder="用一句自然语言描述你要看的数据（回车发送）"
    />

    <el-button
      type="primary"
      native-type="submit"
      name="ask"
      data-testid="ask"
      :loading="busy"
    >
      发送
    </el-button>
  </form>
</template>

<style scoped>
.ask {
  display: flex;
  align-items: center;
  gap: var(--wm-space-3);
  flex-shrink: 0;
  padding: var(--wm-space-3) var(--wm-space-4);
  /* 输入带用实线顶部分隔，与上方消息区拉开区分度（细线属令牌纪律声明的极少数例外） */
  border-top: 1px solid var(--wm-border-hairline);
  background-color: var(--wm-bg-subtle);
}

/* 图标底座：与客服侧的 composer 同形，白底方章把图标从灰底上托起来 */
.ask__icon {
  display: grid;
  place-items: center;
  flex-shrink: 0;
  width: var(--wm-space-5);
  height: var(--wm-space-5);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-card);
  color: var(--wm-text-muted);
  /* el-icon 的 svg 以 1em 计，font-size 即图标尺寸 */
  font-size: var(--wm-space-4);
}

.ask__input {
  flex: 1;
}
</style>
