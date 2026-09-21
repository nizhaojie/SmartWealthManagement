<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, PageHeader, PanelCard } from "@wealth/shared";
import { errorMessage } from "../format";
import CustomerInspector from "../inspector/CustomerInspector.vue";
import { useInspector } from "../shell/pageSlots";
import { useAuthStore } from "../stores/auth";
import { useCurrentCustomerStore } from "../stores/currentCustomer";
import AdvisoryCommentsPanel from "./AdvisoryCommentsPanel.vue";
import DraftVersionsPanels from "./DraftVersionsPanels.vue";
import ReviewDecisionPanel from "./ReviewDecisionPanel.vue";
import {
  getDraft,
  getFinal,
  getReviewStatus,
  listComments,
  postComment,
  releaseDraft,
  rejectDraft,
} from "./api";
import { canReview, isDecided, toCandidatePayload } from "./reviewView";
import { useAdvisoryQueueStore } from "./queueStore";
import type {
  AdvisoryComment,
  AdvisoryDraft,
  AdvisoryFinal,
  AdvisoryReviewStatus,
  EditableCandidate,
} from "./types";

/**
 * 审核页：护栏「未审核内容不可送达」在前端的落点。
 *
 * 左列是 AI 原稿（永久留存），右列放行前是顾问编辑版本、放行后换成顾问定稿。
 * 放行与驳回都只对理财顾问开放；其他角色只能查看与留言（后端也会再挡一次）。
 *
 * 本页同时承担两个场景：待审时是「审核」，已放行 / 已驳回时退化为只读回看——
 * 标题、面包屑与返回文案跟着 `decided` 走，决定面板由它挡住。往本页加功能前先问
 * 它此刻代表哪一个。
 */
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const currentCustomer = useCurrentCustomerStore();
// 放行 / 驳回之后这条内容离开待审队列，壳上的角标要跟着掉。
const queue = useAdvisoryQueueStore();

const draftId = computed(() => Number(route.params.draftId));

const draft = ref<AdvisoryDraft | null>(null);
const review = ref<AdvisoryReviewStatus | null>(null);
const final = ref<AdvisoryFinal | null>(null);
const comments = ref<AdvisoryComment[]>([]);

const loading = ref(true);
const forbidden = ref(false);
const forbiddenMessage = ref("");
const loadError = ref("");

const editedCandidates = ref<EditableCandidate[]>([]);
const editedAllocation = ref<Record<string, number>>({});

const actionError = ref("");
const submitting = ref(false);
const commentError = ref("");
const commentSubmitting = ref(false);

const isAdvisor = computed(() => canReview(auth.currentEmployee?.employee_role));
const decided = computed(() => isDecided(review.value?.status));
const editable = computed(() => isAdvisor.value && !decided.value);

// 同一页两种场景：待审是「审核」，已决定是回看。标题与返回去向都跟着场景走。
const pageTitle = computed(() => (decided.value ? "查看方案" : "审核"));
const breadcrumb = computed(() => ["投顾助手", pageTitle.value]);
const backLabel = computed(() => (decided.value ? "返回投顾助手" : "返回队列"));

async function loadComments(): Promise<void> {
  try {
    comments.value = await listComments(draftId.value);
  } catch {
    // 留言拉不到不影响审核本身，保留已加载的部分。
  }
}

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  forbidden.value = false;
  final.value = null;

  if (!Number.isFinite(draftId.value)) {
    loadError.value = "审核单号无效";
    loading.value = false;
    return;
  }

  try {
    const [nextDraft, nextReview] = await Promise.all([
      getDraft(draftId.value),
      getReviewStatus(draftId.value),
    ]);
    draft.value = nextDraft;
    review.value = nextReview;
    editedCandidates.value = nextDraft.candidates.map((candidate) => ({
      ...candidate,
      included: true,
    }));
    editedAllocation.value = { ...nextDraft.allocation_suggestion };
    // 审核的是某位客户的方案，检查器跟着显示这位客户。
    currentCustomer.setCustomer(nextDraft.customer_id);

    if (nextReview.status === "已放行") {
      final.value = await getFinal(draftId.value);
    }
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
    final.value = await releaseDraft(draftId.value, {
      candidates: toCandidatePayload(editedCandidates.value),
      allocationSuggestion: { ...editedAllocation.value },
    });
    review.value = { draft_id: draftId.value, status: "已放行" };
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
    await rejectDraft(draftId.value, reason);
    review.value = { draft_id: draftId.value, status: "已驳回" };
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
    await postComment(draftId.value, body);
    await loadComments();
  } catch (error) {
    commentError.value = errorMessage(error, "留言失败");
  } finally {
    commentSubmitting.value = false;
  }
}

function backToWorkspace(): void {
  void router.push("/advisory");
}

useInspector(() => ({ component: CustomerInspector }));

watch(draftId, load, { immediate: true });
</script>

<template>
  <div class="review">
    <PageHeader :title="pageTitle" :breadcrumb="breadcrumb">
      <template #actions>
        <el-button
          size="small"
          name="back-to-workspace"
          data-testid="back-to-workspace"
          @click="backToWorkspace"
        >
          {{ backLabel }}
        </el-button>
      </template>
    </PageHeader>

    <p v-if="forbidden" class="review__forbidden" role="alert" data-testid="review-forbidden">
      {{ forbiddenMessage || "无权查看这份方案" }}
    </p>
    <p v-else-if="loadError" class="review__error" role="alert" data-testid="review-error">
      {{ loadError }}
    </p>
    <p v-else-if="loading" class="review__hint">加载中…</p>

    <template v-else-if="draft">
      <p class="review__status" data-testid="review-status">
        当前状态：{{ review?.status ?? "待审" }}
      </p>

      <el-alert
        v-for="warning in draft.warnings"
        :key="warning.code"
        type="warning"
        :closable="false"
        :title="warning.message"
        data-testid="draft-warning"
      />

      <DraftVersionsPanels
        :draft="draft"
        :final="final"
        :candidates="editedCandidates"
        :allocation="editedAllocation"
        :editable="editable"
      />

      <ReviewDecisionPanel
        v-if="isAdvisor && !decided"
        :submitting="submitting"
        :error="actionError"
        @release="submitRelease"
        @reject="submitReject"
      />
      <PanelCard v-else-if="!decided" title="审核决定">
        <p class="review__hint" data-testid="no-release-entry">
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
.review {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.review__status {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.review__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
}

.review__error,
.review__forbidden {
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
