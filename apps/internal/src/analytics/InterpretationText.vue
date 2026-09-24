<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { createTypewriter } from "./typewriter";

// 逐字间隔（毫秒）。后端整轮跑完才把定案回答交给前端（不新增流式端点），所以节奏全靠
// 前端这一处压；调观感只改这个数。与客服同一档（`ChatPage.vue` 的 30）。
const TYPEWRITER_INTERVAL_MS = 30;

// 伪流式只作用于解读这一段：整包到达后逐字上屏，表格与 SQL 等它播完再出现——
// 「播完」由 `done` 报出去，外框据此放出结果面。
//
// `typing` 说的是「这一轮是刚到的」：只有刚到的轮次才逐字播。读回的历史轮次
// （刷新、切模块回来）是全文直出——20 轮一起重新逐字播放不是「逐字感」，是把页面拖住。
const props = defineProps<{ text: string; typing?: boolean }>();
const emit = defineEmits<{ grow: []; done: [] }>();

const shown = ref("");
const typewriter = createTypewriter(TYPEWRITER_INTERVAL_MS, (char) => {
  shown.value += char;
  // 每长一个字就告诉外框一声：解读把气泡撑高时，线程得跟着往下贴。
  emit("grow");
});

// 只播一遍：这一轮的解读是定案文本，不是增量流。text 换了就从头重播。
watch(
  [() => props.text, () => props.typing],
  ([text, typing]) => {
    typewriter.flush();
    if (!typing) {
      shown.value = text;
      return;
    }
    shown.value = "";
    typewriter.push(text);
    // 定案排在缓冲后面：报的是「解读已经上屏完毕」，不是「整包到了」。
    typewriter.end(() => emit("done"));
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
