<script setup lang="ts">
import { ref } from "vue";
import { PanelCard } from "@wealth/shared";

/**
 * 审核决定：放行（把勾选与改后的配置作为顾问定稿送出）或驳回（理由必填）。
 * 理由不是可选项——没有理由的驳回等于把「为什么不行」丢了，AI 与客户都无从改进。
 */
defineProps<{
  submitting: boolean;
  error: string;
}>();

const emit = defineEmits<{
  release: [];
  reject: [reason: string];
}>();

const rejectReason = ref("");
const localError = ref("");

function submitReject(): void {
  const reason = rejectReason.value.trim();
  if (!reason) {
    localError.value = "驳回理由不能为空";
    return;
  }
  localError.value = "";
  emit("reject", reason);
}

function submitRelease(): void {
  localError.value = "";
  emit("release");
}
</script>

<template>
  <PanelCard title="审核决定" data-testid="review-decision">
    <div class="decision">
      <el-button
        type="primary"
        name="release"
        data-testid="release"
        :loading="submitting"
        @click="submitRelease"
      >
        放行
      </el-button>
      <el-input
        v-model="rejectReason"
        name="reject-reason"
        placeholder="驳回理由（必填）"
        data-testid="reject-reason"
        class="decision__reason"
      />
      <el-button
        type="danger"
        name="reject"
        data-testid="reject"
        :disabled="!rejectReason.trim()"
        :loading="submitting"
        @click="submitReject"
      >
        驳回
      </el-button>
    </div>

    <p v-if="localError" class="decision__error" role="alert" data-testid="decision-error">
      {{ localError }}
    </p>
    <p v-if="error" class="decision__error" role="alert" data-testid="action-error">
      {{ error }}
    </p>
  </PanelCard>
</template>

<style scoped>
.decision {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wm-space-3);
}

.decision__reason {
  flex: 1;
  min-width: calc(var(--wm-space-6) * 8);
}

.decision__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
