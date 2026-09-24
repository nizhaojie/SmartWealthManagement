<script setup lang="ts">
// 用户气泡：右对齐、按内容限宽。宽度跟着问题走，短问题不该被拉成一整行。
defineProps<{ question: string }>();
</script>

<template>
  <article class="user-bubble" data-role="user" data-testid="user-bubble">
    <p class="user-bubble__text">{{ question }}</p>
  </article>
</template>

<style scoped>
.user-bubble {
  align-self: flex-end;
  max-width: 72%;
  padding: var(--wm-space-3) var(--wm-space-4);
  border-radius: var(--wm-radius-lg);
  background-color: var(--wm-bg-user-bubble);
  box-shadow: var(--wm-shadow-card);
}

.user-bubble__text {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
