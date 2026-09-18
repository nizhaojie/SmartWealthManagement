<script setup lang="ts">
import { ref } from "vue";
import { PanelCard } from "@wealth/shared";
import { formatDateTime } from "../format";
import type { AdvisoryComment } from "./types";

// 留言：审核过程中的讨论留痕，不属于投顾内容本身，不参与送达判定。
defineProps<{
  comments: AdvisoryComment[];
  submitting: boolean;
  error: string;
}>();

const emit = defineEmits<{ post: [body: string] }>();

const newComment = ref("");

function submit(): void {
  const body = newComment.value.trim();
  if (!body) return;
  emit("post", body);
  newComment.value = "";
}
</script>

<template>
  <PanelCard title="留言" data-testid="comments-panel">
    <p v-if="!comments.length" class="comments__empty">还没有留言。</p>
    <ul v-else class="comments">
      <li v-for="comment in comments" :key="comment.id" class="comments__item">
        <header class="comments__head">
          <strong>{{ comment.author_name ?? "—" }}（{{ comment.author_role }}）</strong>
          <span class="comments__time">{{ formatDateTime(comment.created_at) }}</span>
        </header>
        <p class="comments__body">{{ comment.body }}</p>
      </li>
    </ul>

    <div class="comments__compose">
      <el-input
        v-model="newComment"
        name="comment"
        type="textarea"
        :rows="2"
        placeholder="写一条留言"
        data-testid="comment-input"
      />
      <el-button
        name="post-comment"
        data-testid="post-comment"
        :disabled="!newComment.trim()"
        :loading="submitting"
        @click="submit"
      >
        发送
      </el-button>
    </div>
    <p v-if="error" class="comments__error" role="alert" data-testid="comment-error">
      {{ error }}
    </p>
  </PanelCard>
</template>

<style scoped>
.comments {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
  margin: 0 0 var(--wm-space-4);
  padding: 0;
  list-style: none;
}

.comments__item {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  padding: var(--wm-space-3);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
}

.comments__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--wm-space-2);
  font-size: 0.8rem;
  color: var(--wm-text-primary);
}

.comments__time {
  color: var(--wm-text-muted);
  font-variant-numeric: tabular-nums;
}

.comments__body {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  line-height: 1.7;
}

.comments__empty {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.comments__compose {
  display: flex;
  align-items: flex-end;
  gap: var(--wm-space-3);
}

.comments__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
