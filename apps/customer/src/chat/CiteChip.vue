<script setup lang="ts">
// 引用角标：客服链路的合规呈现面。它必须始终可点、可定位，
// 改动样式时不许牺牲这两个性质（有测试盯着）。
defineProps<{
  marker: string;
  open: boolean;
  panelId: string;
}>();

const emit = defineEmits<{ toggle: [] }>();
</script>

<template>
  <button
    type="button"
    class="cite-chip"
    :aria-expanded="open"
    :aria-controls="panelId"
    :data-marker="marker"
    @click="emit('toggle')"
  >
    {{ marker }}
  </button>
</template>

<style scoped>
.cite-chip {
  padding: 0 var(--wm-space-1);
  border: none;
  background: none;
  /* 淡染底之外的可点文字一律走 primary-strong：primary 本身不达 4.5:1 */
  color: var(--wm-color-primary-strong);
  font-size: 0.75em;
  font-weight: 700;
  vertical-align: super;
  cursor: pointer;
}

.cite-chip:hover {
  text-decoration: underline;
}
</style>
