<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ApiError, SectionCard } from "@wealth/shared";
import { ADVISOR } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import {
  getDraft,
  getFinal,
  getReviewStatus,
  listComments,
  postComment,
  rejectDraft,
  releaseDraft,
} from "./api";
import type {
  AdvisoryCandidate,
  AdvisoryComment,
  AdvisoryDraft,
  AdvisoryFinal,
  AdvisoryReviewStatus,
} from "./types";

const route = useRoute();
const router = useRouter();

const draftId = computed(() => Number(route.params.draftId));
const isAdvisor = computed(() => currentEmployee.value?.employee_role === ADVISOR);

const draft = ref<AdvisoryDraft | null>(null);
const review = ref<AdvisoryReviewStatus | null>(null);
const final = ref<AdvisoryFinal | null>(null);
const comments = ref<AdvisoryComment[]>([]);

const loading = ref(true);
const forbidden = ref(false);
const forbiddenMessage = ref("");
const loadError = ref("");

const editedCandidates = ref<(AdvisoryCandidate & { included: boolean })[]>([]);
const editedAllocation = ref<Record<string, number>>({});

const rejectReason = ref("");
const actionError = ref("");
const submitting = ref(false);

const newComment = ref("");
const commentError = ref("");

const isDecided = computed(
  () => review.value?.status === "已放行" || review.value?.status === "已驳回",
);

const removedCount = computed(
  () => editedCandidates.value.filter((candidate) => !candidate.included).length,
);

function changedAllocationKeys(): string[] {
  if (!draft.value) return [];
  return Object.keys(editedAllocation.value).filter(
    (key) => editedAllocation.value[key] !== draft.value?.allocation_suggestion[key],
  );
}

async function load() {
  loading.value = true;
  forbidden.value = false;
  loadError.value = "";
  try {
    const [loadedDraft, loadedReview] = await Promise.all([
      getDraft(draftId.value),
      getReviewStatus(draftId.value),
    ]);
    draft.value = loadedDraft;
    review.value = loadedReview;
    editedCandidates.value = loadedDraft.candidates.map((candidate) => ({
      ...candidate,
      included: true,
    }));
    editedAllocation.value = { ...loadedDraft.allocation_suggestion };

    if (loadedReview.status === "已放行") {
      final.value = await getFinal(draftId.value);
    }
    comments.value = await listComments(draftId.value);
  } catch (error) {
    if (error instanceof ApiError && error.code === 403) {
      forbidden.value = true;
      // 403 有两种成因（角色不对 / 角色对但不是这位客户的经理），后端的
      // message 已经分得清楚，直接透传，不要用一句写死的话盖过它。
      forbiddenMessage.value = error.message;
    } else {
      loadError.value = error instanceof ApiError ? error.message : "加载审核内容失败";
    }
  } finally {
    loading.value = false;
  }
}

function backToQueue() {
  router.push({ name: "advisory" });
}

async function submitRelease() {
  actionError.value = "";
  submitting.value = true;
  try {
    const candidates = editedCandidates.value
      .filter((candidate) => candidate.included)
      .map(({ included: _included, ...candidate }) => candidate);
    final.value = await releaseDraft(draftId.value, {
      candidates,
      allocationSuggestion: editedAllocation.value,
    });
    review.value = { draft_id: draftId.value, status: "已放行" };
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.message : "放行失败";
  } finally {
    submitting.value = false;
  }
}

async function submitReject() {
  if (!rejectReason.value.trim()) return;
  actionError.value = "";
  submitting.value = true;
  try {
    await rejectDraft(draftId.value, rejectReason.value.trim());
    review.value = { draft_id: draftId.value, status: "已驳回" };
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.message : "驳回失败";
  } finally {
    submitting.value = false;
  }
}

async function submitComment() {
  if (!newComment.value.trim()) return;
  commentError.value = "";
  try {
    const comment = await postComment(draftId.value, newComment.value.trim());
    comments.value = [...comments.value, comment];
    newComment.value = "";
  } catch (error) {
    commentError.value = error instanceof ApiError ? error.message : "发送留言失败";
  }
}

function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

onMounted(load);
</script>

<template>
  <div class="advisory-review" data-test="advisory-review-page">
    <p v-if="loading">加载中…</p>
    <SectionCard v-else-if="forbidden" title="无权查看" data-test="forbidden">
      <p role="alert">{{ forbiddenMessage }}</p>
    </SectionCard>
    <p v-else-if="loadError" class="advisory-review__error" data-test="load-error">{{ loadError }}</p>

    <template v-else-if="draft && review">
      <header class="advisory-review__header">
        <el-button data-test="back-to-queue" @click="backToQueue">返回队列</el-button>
        <span data-test="review-status">当前状态：{{ review.status }}</span>
      </header>

      <el-alert
        v-for="warning in draft.warnings"
        :key="warning.code"
        type="warning"
        :closable="false"
        :title="warning.message"
        data-test="draft-warning"
        class="advisory-review__warning"
      />

      <div class="advisory-review__panels">
        <SectionCard title="AI 原稿" data-test="original-panel">
          <el-table :data="draft.candidates" row-key="product_code">
            <el-table-column type="expand">
              <template #default="{ row }">
                <ul class="advisory-review__breakdown" data-test="score-breakdown">
                  <li v-for="item in row.score_breakdown" :key="item.dimension">
                    {{ item.dimension }}：{{ item.raw_value }}，得分 {{ item.score }} ×
                    权重 {{ item.weight }} = 贡献 {{ item.contribution }}
                  </li>
                </ul>
              </template>
            </el-table-column>
            <el-table-column prop="product_name" label="产品" />
            <el-table-column prop="risk_level" label="风险等级" />
            <el-table-column prop="composite_score" label="综合得分" />
          </el-table>
          <h3 class="advisory-review__subheading">配置建议</h3>
          <ul class="advisory-review__allocation">
            <li v-for="(value, key) in draft.allocation_suggestion" :key="key">
              {{ key }}：{{ value }}%
            </li>
          </ul>
        </SectionCard>

        <SectionCard title="编辑版本" data-test="edited-panel">
          <p v-if="removedCount" class="advisory-review__diff-note" data-test="removed-note">
            已从原稿移除 {{ removedCount }} 项推荐产品
          </p>
          <el-table :data="editedCandidates" row-key="product_code">
            <el-table-column type="expand">
              <template #default="{ row }">
                <ul class="advisory-review__breakdown" data-test="score-breakdown-edited">
                  <li v-for="item in row.score_breakdown" :key="item.dimension">
                    {{ item.dimension }}：{{ item.raw_value }}，得分 {{ item.score }} ×
                    权重 {{ item.weight }} = 贡献 {{ item.contribution }}
                  </li>
                </ul>
              </template>
            </el-table-column>
            <el-table-column label="保留">
              <template #default="{ row }">
                <el-checkbox v-model="row.included" data-test="candidate-include" :disabled="isDecided || !isAdvisor" />
              </template>
            </el-table-column>
            <el-table-column prop="product_name" label="产品">
              <template #default="{ row }">
                <span :class="{ 'is-removed': !row.included }">{{ row.product_name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="risk_level" label="风险等级" />
            <el-table-column prop="composite_score" label="综合得分" />
          </el-table>
          <h3 class="advisory-review__subheading">配置建议</h3>
          <ul class="advisory-review__allocation">
            <li v-for="(_value, key) in editedAllocation" :key="key">
              {{ key }}：
              <el-input-number
                v-model="editedAllocation[key]"
                :min="0"
                :max="100"
                size="small"
                :disabled="isDecided || !isAdvisor"
                data-test="allocation-input"
              />
              <span v-if="changedAllocationKeys().includes(key)" class="advisory-review__changed" data-test="allocation-changed">
                （原 {{ draft.allocation_suggestion[key] }}%）
              </span>
            </li>
          </ul>
        </SectionCard>
      </div>

      <SectionCard v-if="isAdvisor && !isDecided" title="审核决定" class="advisory-review__actions">
        <el-button type="primary" data-test="release" :loading="submitting" @click="submitRelease">
          放行
        </el-button>
        <div class="advisory-review__reject">
          <el-input
            v-model="rejectReason"
            type="textarea"
            :rows="2"
            placeholder="驳回理由（必填）"
            data-test="reject-reason"
          />
          <el-button
            type="danger"
            data-test="reject"
            :disabled="!rejectReason.trim()"
            :loading="submitting"
            @click="submitReject"
          >
            驳回
          </el-button>
        </div>
        <p v-if="actionError" class="advisory-review__error" data-test="action-error">{{ actionError }}</p>
      </SectionCard>
      <p v-else-if="!isAdvisor && !isDecided" class="advisory-review__hint" data-test="no-release-entry">
        当前角色无法放行或驳回，仅可查看与留言。
      </p>

      <SectionCard v-if="final" title="顾问定稿" data-test="final-panel">
        <p>放行人：{{ final.advisor_name }} · {{ formatDateTime(final.released_at) }}</p>
      </SectionCard>

      <SectionCard title="留言" data-test="comments-panel">
        <ul class="advisory-review__comments">
          <li v-for="comment in comments" :key="comment.id">
            <strong>{{ comment.author_name }}（{{ comment.author_role }}）</strong>
            <span>{{ formatDateTime(comment.created_at) }}</span>
            <p>{{ comment.body }}</p>
          </li>
        </ul>
        <div class="advisory-review__comment-form">
          <el-input
            v-model="newComment"
            type="textarea"
            :rows="2"
            placeholder="写一条留言"
            data-test="comment-input"
          />
          <el-button data-test="post-comment" :disabled="!newComment.trim()" @click="submitComment">
            发送
          </el-button>
        </div>
        <p v-if="commentError" class="advisory-review__error">{{ commentError }}</p>
      </SectionCard>
    </template>
  </div>
</template>

<style scoped>
.advisory-review {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.advisory-review__header {
  display: flex;
  align-items: center;
  gap: var(--wm-space-4);
}

.advisory-review__panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--wm-space-4);
}

.advisory-review__subheading {
  margin: var(--wm-space-3) 0;
  color: var(--wm-text-primary);
}

.advisory-review__breakdown {
  margin: 0;
  padding-left: var(--wm-space-5);
}

.advisory-review__allocation {
  list-style: none;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--wm-space-3);
  color: var(--wm-text-primary);
}

.is-removed {
  text-decoration: line-through;
  color: var(--wm-text-muted);
}

.advisory-review__changed {
  color: var(--wm-color-warning);
  font-size: 12px;
}

.advisory-review__diff-note {
  color: var(--wm-color-warning);
}

.advisory-review__reject {
  display: flex;
  gap: var(--wm-space-2);
  align-items: flex-start;
  margin-top: var(--wm-space-3);
}

.advisory-review__error {
  color: var(--wm-color-danger);
}

.advisory-review__hint {
  color: var(--wm-text-muted);
}

.advisory-review__comments {
  list-style: none;
  padding: 0;
  margin: 0;
}

.advisory-review__comments li {
  /* 留言间的 1px 虚线分隔（令牌纪律声明的极少数例外） */
  border-bottom: 1px dashed var(--wm-border-hairline);
  padding: var(--wm-space-2) 0;
}

.advisory-review__comments span {
  margin-left: var(--wm-space-2);
  color: var(--wm-text-muted);
  font-size: 12px;
}

.advisory-review__comment-form {
  display: flex;
  gap: var(--wm-space-2);
  margin-top: var(--wm-space-3);
}

@media (max-width: 900px) {
  .advisory-review__panels {
    grid-template-columns: 1fr;
  }
}
</style>
