<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { createTypewriter } from "./typewriter";

// 逐字间隔（毫秒）。后端整轮跑完才把定案回答交给前端（不新增流式端点），所以节奏全靠
// 前端这一处压；调观感只改这个数。与客服同一档（`ChatPage.vue` 的 30）。
const TYPEWRITER_INTERVAL_MS = 30;

// 伪流式只作用于解读这一段：整包到达后逐字上屏，表格与 SQL 等它播完再出现（见 04）。
// 打字机是页面内的一次性播放器，不落任何全局状态——重挂载即重播，不跨轮共享。
const props = defineProps<{ text: string }>();

const shown = ref("");
const typewriter = createTypewriter(TYPEWRITER_INTERVAL_MS, (char) => {
  shown.value += char;
});

// 只播一遍：这一轮的解读是定案文本，不是增量流。text 换了就从头重播。
watch(
  () => props.text,
  (text) => {
    typewriter.flush();
    shown.value = "";
    typewriter.push(text);
  },
  { immediate: true },
);

// 组件在播放中途被卸载（切模块、清空对话）时把缓冲丢掉，不再往已卸掉的节点上写。
onBeforeUnmount(() => {
  typewriter.flush();
});
</script>

<template>
  <p class="interpretation" data-testid="interpretation">{{ shown }}</p>
</template>

<style scoped>
.interpretation {
  margin: 0;
  /* 文本没有换行提示时按字断行：长口径解读不至于把气泡撑宽 */
  word-break: break-word;
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  line-height: 1.8;
  /* 解读里模型给的换行原样保留 */
  white-space: pre-wrap;
}
</style>
