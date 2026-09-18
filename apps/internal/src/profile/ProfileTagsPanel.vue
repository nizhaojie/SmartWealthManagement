<script setup lang="ts">
import { computed, ref } from "vue";
import { MeterBar, PanelCard } from "@wealth/shared";
import { formatValue, toPercent } from "../format";
import { DIMENSION_ORDER, parseCorrectionValue } from "./profileView";
import type { DimensionScores, ProfileTag } from "./types";

// 标签瓦片 + 手工修正 + 四维度明细。修正必须填理由：它是画像变更的留痕，不是可选项。
const props = defineProps<{
  tags: ProfileTag[];
  dimensionScores: DimensionScores | null;
}>();

const emit = defineEmits<{
  correct: [payload: { tagKey: string; value: unknown; reason: string }];
}>();

const showDimensions = ref(false);

const correcting = ref<ProfileTag | null>(null);
const correctionOpen = ref(false);
const correctionValue = ref("");
const correctionReason = ref("");
const correctionError = ref("");

const dimensions = computed(() => {
  const scores = props.dimensionScores;
  if (!scores) return [];
  return DIMENSION_ORDER.map((name) => ({ name, score: scores[name] }));
});

function openCorrection(tag: ProfileTag): void {
  correcting.value = tag;
  correctionValue.value = typeof tag.value === "string" ? tag.value : JSON.stringify(tag.value);
  correctionReason.value = "";
  correctionError.value = "";
  correctionOpen.value = true;
}

function submitCorrection(): void {
  const tag = correcting.value;
  if (!tag) return;
  if (!correctionReason.value.trim()) {
    correctionError.value = "手工修正必须填写理由";
    return;
  }

  let value: unknown;
  try {
    value = parseCorrectionValue(correctionValue.value, tag.value);
  } catch {
    correctionError.value = "值不是合法的 JSON";
    return;
  }

  emit("correct", { tagKey: tag.key, value, reason: correctionReason.value.trim() });
  correctionOpen.value = false;
}
</script>

<template>
  <PanelCard title="画像标签">
    <ul class="tags">
      <li v-for="tag in tags" :key="tag.key" class="tags__item">
        <header class="tags__head">
          <span class="tags__label">{{ tag.label }}</span>
          <span class="tags__source">{{ tag.source }}</span>
          <span v-if="tag.expired" class="tags__expired" data-testid="tag-expired">已过期</span>
        </header>
        <p class="tags__value">{{ formatValue(tag.value) }}</p>
        <div class="tags__footer">
          <div class="tags__meter">
            <MeterBar label="置信度" :percent="toPercent(tag.confidence)" />
          </div>
          <button
            type="button"
            class="tags__correct"
            name="correct-tag"
            data-testid="correct-tag"
            @click="openCorrection(tag)"
          >
            修正
          </button>
        </div>
      </li>
    </ul>

    <div v-if="dimensionScores" class="dimensions">
      <button
        type="button"
        class="dimensions__toggle"
        name="dimension-toggle"
        data-testid="dimension-toggle"
        @click="showDimensions = !showDimensions"
      >
        {{ showDimensions ? "收起四个维度" : "展开四个维度" }}
      </button>
      <dl v-if="showDimensions" class="dimensions__list" data-testid="dimension-scores">
        <div v-for="dimension in dimensions" :key="dimension.name" class="dimensions__row">
          <dt>{{ dimension.name }}</dt>
          <dd>{{ dimension.score }}</dd>
        </div>
      </dl>
    </div>

    <el-dialog
      v-model="correctionOpen"
      :title="correcting ? `修正 ${correcting.label}` : '修正标签'"
      width="420px"
    >
      <label class="correction__field">
        <span class="correction__label">新值</span>
        <el-input v-model="correctionValue" name="correction-value" data-testid="correction-value" />
      </label>
      <label class="correction__field">
        <span class="correction__label">理由（必填）</span>
        <el-input
          v-model="correctionReason"
          name="correction-reason"
          type="textarea"
          :rows="3"
          data-testid="correction-reason"
        />
      </label>
      <p v-if="correctionError" class="correction__error" role="alert" data-testid="correction-error">
        {{ correctionError }}
      </p>

      <template #footer>
        <el-button @click="correctionOpen = false">取消</el-button>
        <el-button type="primary" data-testid="save-correction" @click="submitCorrection">
          保存修正
        </el-button>
      </template>
    </el-dialog>
  </PanelCard>
</template>

<style scoped>
.tags {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(calc(var(--wm-space-6) * 6), 1fr));
  gap: var(--wm-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.tags__item {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  padding: var(--wm-space-3);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
}

.tags__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wm-space-2);
}

/* 淡染底上的文字走 primary-strong */
.tags__label {
  padding: 0 var(--wm-space-2);
  border-radius: var(--wm-radius-pill);
  background-color: var(--wm-color-primary-tint);
  color: var(--wm-color-primary-strong);
  font-size: 0.75rem;
  font-weight: 600;
}

.tags__source {
  color: var(--wm-text-muted);
  font-size: 0.75rem;
}

.tags__expired {
  color: var(--wm-color-danger);
  font-size: 0.75rem;
}

.tags__value {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  line-height: 1.6;
}

.tags__footer {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
}

.tags__meter {
  flex: 1;
  min-width: 0;
}

.tags__correct {
  padding: var(--wm-space-1) var(--wm-space-2);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-card);
  color: var(--wm-text-muted);
  font-family: inherit;
  font-size: 0.75rem;
  cursor: pointer;
}

.tags__correct:hover {
  color: var(--wm-text-primary);
}

.dimensions {
  margin-top: var(--wm-space-4);
}

.dimensions__toggle {
  padding: var(--wm-space-1) var(--wm-space-3);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-card);
  color: var(--wm-text-muted);
  font-family: inherit;
  font-size: 0.8rem;
  cursor: pointer;
}

.dimensions__list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(calc(var(--wm-space-6) * 4), 1fr));
  gap: var(--wm-space-2);
  margin: var(--wm-space-3) 0 0;
}

.dimensions__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--wm-space-2);
  padding: var(--wm-space-2) var(--wm-space-3);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
}

.dimensions__row dt {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.dimensions__row dd {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}

.correction__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  margin-bottom: var(--wm-space-3);
}

.correction__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.correction__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}
</style>
