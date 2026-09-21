<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, PageHeader, PanelCard } from "@wealth/shared";
import AdvisoryCommentsPanel from "../advisory/AdvisoryCommentsPanel.vue";
import ReviewDecisionPanel from "../advisory/ReviewDecisionPanel.vue";
import { canReview, isDecided } from "../advisory/reviewView";
import { useAdvisoryQueueStore } from "../advisory/queueStore";
import type { AdvisoryComment } from "../advisory/types";
import { ADVISOR } from "../auth/identity";
import { errorMessage } from "../format";
import CustomerInspector from "../inspector/CustomerInspector.vue";
import { useInspector } from "../shell/pageSlots";
import { useAuthStore } from "../stores/auth";
import { useCurrentCustomerStore } from "../stores/currentCustomer";
import AdvicePayloadPanel from "./AdvicePayloadPanel.vue";
import {
  getAdvice,
  getAdviceReview,
  listAdviceComments,
  postAdviceComment,
  rejectAdvice,
  releaseAdvice,
} from "./api";
import type { AdviceReviewStatus, OperationAdvice } from "./types";

/**
 * 操作建议的审核页：审核队列里那一类内容的打开处。
 *
 * 与方案审核页（`advisory/AdvisoryReviewPage.vue`）是同一个场景的两种载荷，因此共用
 * 放行 / 驳回面板、留言面板与「资质决定入口」这三条规则，但**不共用载荷的渲染件**——
 * 方案特有的字段（候选池、配置建议）在这里一个都不出现（issue 09 的第三条断言）。
 *
 * 本页同样承担两个场景：待审时是「审核」，已放行 / 已驳回时退化为只读回看。往本页
 * 加功能前先问它此刻代表哪一个。
 *
 * 客户经理也会打开本页（他的入口在客户关系模块的进度表里）：他读得到、留言得了，
 * 但没有放行与驳回入口——那一半由 `canReview` 挡住，后端再挡一次。
 */
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const currentCustomer = useCurrentCustomerStore();
// 放行 / 驳回之后这条内容离开待审队列，壳上的角标要跟着掉。
const queue = useAdvisoryQueueStore();

const adviceId = computed(() => Number(route.params.adviceId));

const advice = ref<OperationAdvice | null>(null);
const review = ref<AdviceReviewStatus | null>(null);
const comments = ref<AdvisoryComment[]>([]);

const loading = ref(true);
const forbidden = ref(false);
const forbiddenMessage = ref("");
const loadError = ref("");

const actionError = ref("");
const submitting = ref(false);
const commentError = ref("");
const commentSubmitting = ref(false);

const isAdvisor = computed(() => canReview(auth.currentEmployee?.employee_role));
const decided = computed(() => isDecided(review.value?.status));

// 同一页两种场景：待审是「审核」，已决定是回看。标题与返回去向都跟着场景走。
const pageTitle = computed(() => (decided.value ? "查看操作建议" : "审核操作建议"));
const breadcrumb = computed(() => ["投顾助手", pageTitle.value]);

// 客户经理从「客户关系」的进度表点进来，理财顾问从审核队列点进来——返回的是他来的地方。
const backTarget = computed(() =>
  auth.currentEmployee?.employee_role === ADVISOR
    ? { path: "/advisory", label: "返回队列" }
    : { path: "/customer-relations", label: "返回客户关系" },
);

async function loadComments(): Promise<void> {
  try {
    comments.value = await listAdviceComments(adviceId.value);
  } catch {
    // 留言拉不到不影响审核本身，保留已加载的那部分。
  }
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  forbidden.value = false;
  advice.value = null;

  if (!Number.isFinite(adviceId.value)) {
    loadError.value = "建议编号无效";
    loading.value = false;
    return;
  }

  try {
    const [nextAdvice, nextReview] = await Promise.all([
      getAdvice(adviceId.value),
      getAdviceReview(adviceId.value),
    ]);
    advice.value = nextAdvice;
    review.value = nextReview;
    // 审核的是某位客户的建议，检查器跟着显示这位客户。
    currentCustomer.setCustomer(nextAdvice.customer_id);
    await loadComments();
  } catch (error) {
    if (error instanceof ApiError && error.code === 403) {
      forbidden.value = true;
      forbiddenMessage.value = error.message;
    } else {
      loadError.value = errorMessage(error, "审核资料加载失败");
    }
  } finally {
    loading.value = false;
  }
}

async function submitRelease(): Promise<void> {
  actionError.value = "";
  submitting.value = true;
  try {
    await releaseAdvice(adviceId.value);
    review.value = { advice_id: adviceId.value, status: "已放行" };
    // 动作成功之后才刷新：失败时内容仍在待审队列里，角标不该动。
    await queue.refresh();
  } catch (error) {
    actionError.value = errorMessage(error, "放行失败");
  } finally {
    submitting.value = false;
  }
}

async function submitReject(reason: string): Promise<void> {
  actionError.value = "";
  submitting.value = true;
  try {
    await rejectAdvice(adviceId.value, reason);
    review.value = { advice_id: adviceId.value, status: "已驳回" };
    await queue.refresh();
  } catch (error) {
    actionError.value = errorMessage(error, "驳回失败");
  } finally {
    submitting.value = false;
  }
}

async function submitComment(body: string): Promise<void> {
  commentError.value = "";
  commentSubmitting.value = true;
  try {
    await postAdviceComment(adviceId.value, body);
    await loadComments();
  } catch (error) {
    commentError.value = errorMessage(error, "留言失败");
  } finally {
    commentSubmitting.value = false;
  }
}

function back(): void {
  void router.push(backTarget.value.path);
}

useInspector(() => ({ component: CustomerInspector }));

watch(adviceId, load, { immediate: true });
</script>

<template>
  <div class="advice-review">
    <PageHeader :title="pageTitle" :breadcrumb="breadcrumb">
      <template #actions>
        <el-button
          size="small"
          name="back-from-advice-review"
          data-testid="back-from-advice-review"
          @click="back"
        >
          {{ backTarget.label }}
        </el-button>
      </template>
    </PageHeader>

    <p
      v-if="forbidden"
      class="advice-review__forbidden"
      role="alert"
      data-testid="advice-review-forbidden"
    >
      {{ forbiddenMessage || "无权查看这条操作建议" }}
    </p>
    <p
      v-else-if="loadError"
      class="advice-review__error"
      role="alert"
      data-testid="advice-review-error"
    >
      {{ loadError }}
    </p>
    <p v-else-if="loading" class="advice-review__hint">加载中…</p>

    <template v-else-if="advice">
      <p class="advice-review__status" data-testid="advice-review-status">
        当前状态：{{ review?.status ?? "待审" }}
      </p>
      <p class="advice-review__meta" data-testid="advice-review-type">
        内容类型：操作建议
      </p>

      <AdvicePayloadPanel :advice="advice" />

      <ReviewDecisionPanel
        v-if="isAdvisor && !decided"
        :submitting="submitting"
        :error="actionError"
        @release="submitRelease"
        @reject="submitReject"
      />
      <PanelCard v-else-if="!decided" title="审核决定">
        <p class="advice-review__hint" data-testid="no-release-entry">
          当前角色无法放行或驳回，仅可查看与留言。
        </p>
      </PanelCard>

      <AdvisoryCommentsPanel
        :comments="comments"
        :submitting="commentSubmitting"
        :error="commentError"
        @post="submitComment"
      />
    </template>
  </div>
</template>

<style scoped>
.advice-review {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.advice-review__status,
.advice-review__meta,
.advice-review__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.advice-review__error,
.advice-review__forbidden {
  margin: 0;
  padding: var(--wm-space-4);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-color-danger);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-card);
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
