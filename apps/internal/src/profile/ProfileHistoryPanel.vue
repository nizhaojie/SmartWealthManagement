<script setup lang="ts">
import { onMounted, watch } from "vue";
import { PaginationBar, PanelCard, usePagination } from "@wealth/shared";
import { formatDateTime, formatValue, gradeCaption } from "../format";
import { listRiskAssessments } from "./api";
import { tagLabel } from "./profileView";
import type { ConflictRecord, RiskAssessmentRecord } from "./types";

/**
 * 历次风险评测与冲突记录：画像「怎么变成现在这样」的两条证据链。
 *
 * 评测历史是一条独立列表（ADR-0024），因此自己按客户标识取、自己翻页，最近的在前。
 * 冲突记录是画像详情内嵌的那一段（不是独立列表资源），跟着画像一起来，保持现状。
 *
 * 它不把这一页交给上层去算「最新的一次」：分页之后 `items[0]` 只是这一页的第一条，
 * 翻到第二页就不再是最新的那次评测了。
 */
const props = defineProps<{
  customerId: number;
  conflicts: ConflictRecord[];
}>();

const {
  items: assessments,
  total,
  page,
  pageSize,
  loading,
  errorMessage: historyError,
  goTo,
  reset,
} = usePagination<RiskAssessmentRecord>(
  (query) => listRiskAssessments(props.customerId, query),
  { failureMessage: "风险评测历史加载失败" },
);

// 换客户是「换了另一位客户的历次评测」，回到第一页重取。
watch(
  () => props.customerId,
  () => {
    void reset();
  },
);

onMounted(() => {
  void reset();
});
</script>

<template>
  <PanelCard title="历次风险评测与冲突记录">
    <section class="block">
      <h4 class="block__title">历次风险评测</h4>
      <p v-if="historyError" class="block__error" role="alert" data-testid="assessment-error">
        {{ historyError }}
      </p>
      <p v-else-if="loading" class="block__hint">加载中…</p>
      <p v-else-if="!assessments.length" class="block__hint" data-testid="assessment-empty">
        还没有风险评测记录。
      </p>

      <ul v-else class="assessments" data-testid="assessment-history">
        <li v-for="item in assessments" :key="item.id" class="assessments__row">
          <span class="assessments__date">{{ item.assessment_date }}</span>
          <span class="assessments__grade">{{ gradeCaption(item.risk_level) }}</span>
          <span class="assessments__valid">有效至 {{ item.valid_until }}</span>
        </li>
      </ul>

      <!-- 取不到时 `total` 归零，分页条与列表同进同退；越界页 `items` 为空但 `total`
           不变，所以它仍然留着——撤掉它，人就困在那一页上。 -->
      <PaginationBar
        v-if="total > 0"
        :total="total"
        :page="page"
        :page-size="pageSize"
        :disabled="loading"
        @update:page="goTo"
      />
    </section>

    <section class="block">
      <h4 class="block__title">冲突记录</h4>
      <p v-if="!conflicts.length" class="block__hint">没有冲突记录。</p>
      <ul v-else class="conflicts" data-testid="conflict-records">
        <li v-for="(record, index) in conflicts" :key="`${record.changed_at}-${index}`" class="conflicts__row">
          <span class="conflicts__time">{{ formatDateTime(record.changed_at) }}</span>
          <span class="conflicts__tag">{{ tagLabel(record.tag_key) }}</span>
          <span class="conflicts__change">
            {{ record.old_source }} 的「{{ formatValue(record.old_value) }}」被
            {{ record.new_source }} 改为「{{ formatValue(record.new_value) }}」
          </span>
        </li>
      </ul>
    </section>
  </PanelCard>
</template>

<style scoped>
.block + .block {
  margin-top: var(--wm-space-5);
}

.block__title {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-primary);
  font-size: 0.88rem;
  font-weight: 600;
}

.block__hint {
  margin: 0;
  color: var(--wm-text-muted);
  font-size: 0.82rem;
}

.block__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.82rem;
}

.assessments,
.conflicts {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.assessments__row,
.conflicts__row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--wm-space-2);
  padding: var(--wm-space-2) var(--wm-space-3);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
  font-size: 0.82rem;
}

.assessments__date,
.conflicts__time {
  color: var(--wm-text-muted);
  font-variant-numeric: tabular-nums;
}

.assessments__grade {
  color: var(--wm-text-primary);
  font-weight: 600;
}

.assessments__valid {
  color: var(--wm-text-muted);
}

.conflicts__tag {
  color: var(--wm-color-primary-strong);
  font-weight: 600;
}

.conflicts__change {
  color: var(--wm-text-primary);
  line-height: 1.6;
}
</style>
