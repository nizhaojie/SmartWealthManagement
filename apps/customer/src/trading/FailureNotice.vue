<script setup lang="ts">
/**
 * 受理失败的一句话 + （能自己解决时）一个入口。
 *
 * 受理失败只有这一种呈现：交易页的三个入口与「我的建议」页的接受，失败时拿到的都是
 * 受理侧的原文（余额不足 / 越级 / 未测评 / 已过期），区别只在「未测评」那一条要顺带
 * 给出风险测评的入口。各页各拼一遍的话，这句话的四种口径迟早只剩三种。
 */
import { useRouter } from "vue-router";
import type { AcceptanceFailure } from "./failure";

const props = defineProps<{ failure: AcceptanceFailure }>();

const router = useRouter();

function goRiskAssessment(): void {
  void router.push({ name: "risk-assessment" });
}
</script>

<template>
  <div class="failure" role="alert" data-testid="trade-failure">
    <span class="failure__message" data-testid="trade-failure-message">
      {{ props.failure.message }}
    </span>
    <el-button
      v-if="props.failure.assessmentRequired"
      size="small"
      name="go-risk-assessment"
      data-testid="go-risk-assessment"
      @click="goRiskAssessment"
    >
      去风险测评
    </el-button>
  </div>
</template>

<style scoped>
.failure {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wm-space-2) var(--wm-space-3);
  margin: var(--wm-space-3) 0 0;
}

.failure__message {
  color: var(--wm-color-danger);
  font-size: 0.85rem;
  line-height: 1.75;
}
</style>
