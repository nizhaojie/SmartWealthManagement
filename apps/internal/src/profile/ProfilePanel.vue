<script setup lang="ts">
import { computed, ref } from "vue";
import AllocationComparisonChart from "./AllocationComparisonChart.vue";
import type { CustomerProfileView, Holding, ProfileTag, RiskAssessmentRecord } from "./types";

const LOW_CONFIDENCE = 0.5;

const TAG_LABELS: Record<string, string> = {
  risk_level: "风险承受等级",
  investment_experience: "投资经验",
  annual_income_range: "收入区间",
  total_assets: "资产规模",
  target_allocation: "目标配置",
  product_preference: "产品偏好",
};

const GRADE_LABELS: Record<string, string> = {
  C1: "保守型",
  C2: "稳健型",
  C3: "平衡型",
  C4: "进取型",
  C5: "激进型",
};

const DIMENSION_ORDER = ["基础属性", "投资经验", "风险偏好", "行为异常"] as const;

const props = withDefaults(
  defineProps<{
    profile: CustomerProfileView;
    assessments?: RiskAssessmentRecord[];
    holdings?: Holding[];
  }>(),
  { assessments: () => [], holdings: () => [] },
);

const emit = defineEmits<{
  correct: [payload: { tagKey: string; value: unknown; reason: string }];
}>();

const showDimensions = ref(false);
const correcting = ref<ProfileTag | null>(null);
const correctionValue = ref("");
const correctionReason = ref("");
const correctionError = ref("");

const computedAtLabel = computed(() => props.profile.computed_at.slice(0, 16).replace("T", " "));

const judgementGrade = computed(() => {
  const level = props.profile.judgement.risk_level;
  if (!level) return null;
  return {
    level,
    label: GRADE_LABELS[level] ?? "",
  };
});

const targetAllocation = computed<Record<string, number>>(() => {
  const tag = props.profile.tags.find((item) => item.key === "target_allocation");
  return (tag?.value as Record<string, number> | undefined) ?? {};
});

const lowConfidenceTags = computed(() =>
  props.profile.tags.filter((tag) => tag.confidence < LOW_CONFIDENCE),
);

const latestAssessment = computed(() => props.assessments.at(-1) ?? null);

const expired = computed(
  () =>
    props.profile.judgement.reasons.some((reason) => reason.code === "ASSESSMENT_EXPIRED") ||
    (latestAssessment.value !== null && latestAssessment.value.valid_until < todayIsoDate()),
);

const warningMessages = computed(() => {
  const messages: string[] = [];
  if (lowConfidenceTags.value.length) {
    messages.push("部分标签置信度偏低，沟通前请核实来源");
  }
  if (expired.value) {
    messages.push("风险评测已过期，请提示客户重新评估");
  }
  return messages;
});

function todayIsoDate(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map((item) => formatValue(item)).join("、");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        if (Array.isArray(item)) return `${key}：${item.map((entry) => formatValue(entry)).join("、")}`;
        if (typeof item === "number") return `${key} ${item}%`;
        return `${key} ${formatValue(item)}`;
      })
      .join(" / ");
  }
  return JSON.stringify(value);
}

function formatConfidence(value: number): string {
  return value.toFixed(2);
}

function tagLabel(key: string): string {
  return TAG_LABELS[key] ?? key;
}

function gradeCaption(level: string): string {
  const label = GRADE_LABELS[level];
  return label ? `${level} ${label}` : level;
}

function parseCorrectionValue(raw: string, original: unknown): unknown {
  const trimmed = raw.trim();
  if (original !== null && typeof original === "object") {
    try {
      return JSON.parse(trimmed) as unknown;
    } catch {
      return trimmed;
    }
  }
  return trimmed;
}

function openCorrection(tag: ProfileTag) {
  correcting.value = tag;
  correctionValue.value =
    tag.value !== null && typeof tag.value === "object"
      ? JSON.stringify(tag.value)
      : typeof tag.value === "string"
        ? tag.value
        : formatValue(tag.value);
  correctionReason.value = "";
  correctionError.value = "";
}

function submitCorrection() {
  if (!correcting.value) return;
  const reason = correctionReason.value.trim();
  if (!reason) {
    correctionError.value = "手工修正必须填写理由";
    return;
  }
  emit("correct", {
    tagKey: correcting.value.key,
    value: parseCorrectionValue(correctionValue.value, correcting.value.value),
    reason,
  });
  correcting.value = null;
}
</script>

<template>
  <article class="customer-file">
    <header class="customer-file__head">
      <div>
        <p class="customer-file__eyebrow">客户画像</p>
        <h2 class="customer-file__name">{{ profile.real_name }}</h2>
      </div>
      <p class="customer-file__date" data-test="computed-at">计算于 {{ computedAtLabel }}</p>
    </header>

    <aside
      v-if="warningMessages.length"
      class="customer-file__warning"
      data-test="profile-warning"
    >
      <p v-for="message in warningMessages" :key="message">{{ message }}</p>
    </aside>

    <section
      v-if="profile.judgement.circuit_break"
      class="customer-file__break"
      data-test="circuit-break"
    >
      <p class="customer-file__stencil customer-file__stencil--void" aria-hidden="true">熔断</p>
      <div>
        <h3>硬性门槛已熔断</h3>
        <p v-for="reason in profile.judgement.reasons" :key="reason.code">{{ reason.message }}</p>
      </div>
    </section>

    <section v-else-if="judgementGrade" class="customer-file__grade">
      <p class="customer-file__stencil" aria-hidden="true">{{ judgementGrade.level }}</p>
      <div>
        <p>四维度研判</p>
        <strong>{{ judgementGrade.level }} {{ judgementGrade.label }}</strong>
      </div>
    </section>

    <AllocationComparisonChart
      class="customer-file__allocation"
      :target-allocation="targetAllocation"
      :holdings="holdings"
    />

    <section class="customer-file__tags">
      <article
        v-for="tag in profile.tags"
        :key="tag.key"
        class="field-card"
        :class="{ 'is-low': tag.confidence < LOW_CONFIDENCE }"
      >
        <div class="field-card__meta">
          <h3>{{ tag.label }}</h3>
          <span class="field-card__source">{{ tag.source }}</span>
        </div>
        <p class="field-card__value">{{ formatValue(tag.value) }}</p>
        <div class="field-card__confidence">
          <span>置信度 {{ formatConfidence(tag.confidence) }}</span>
          <i class="field-card__bar" :style="{ width: `${Math.round(tag.confidence * 100)}%` }" />
        </div>
        <button data-test="correct-tag" class="field-card__correct" type="button" @click="openCorrection(tag)">
          修正
        </button>
      </article>
    </section>

    <section v-if="profile.judgement.dimension_scores" class="customer-file__dimensions">
      <button data-test="dimension-toggle" type="button" @click="showDimensions = !showDimensions">
        {{ showDimensions ? "收起四个维度" : "展开四个维度" }}
      </button>
      <ul v-if="showDimensions">
        <li v-for="name in DIMENSION_ORDER" :key="name">
          <span>{{ name }}</span>
          <strong>{{ profile.judgement.dimension_scores[name] }}</strong>
        </li>
      </ul>
    </section>

    <section v-if="assessments.length" class="customer-file__history" data-test="assessment-history">
      <h3>历次风险评测</h3>
      <ol>
        <li v-for="item in assessments" :key="item.id">
          <time>{{ item.assessment_date }}</time>
          <strong>{{ gradeCaption(item.risk_level) }}</strong>
          <span>有效至 {{ item.valid_until }}</span>
        </li>
      </ol>
    </section>

    <section v-if="profile.conflict_records.length" class="customer-file__conflicts" data-test="conflict-records">
      <h3>冲突记录</h3>
      <ol>
        <li v-for="(record, index) in profile.conflict_records" :key="`${record.tag_key}-${index}`">
          {{ record.changed_at.slice(0, 16).replace("T", " ") }}
          · {{ tagLabel(record.tag_key) }}：{{ record.old_source }} 的「{{ formatValue(record.old_value) }}」
          被 {{ record.new_source }} 改为「{{ formatValue(record.new_value) }}」
        </li>
      </ol>
    </section>

    <div v-if="correcting" class="customer-file__dialog">
      <h3>修正 {{ correcting.label }}</h3>
      <label>
        新值
        <input v-model="correctionValue" name="correction-value" />
      </label>
      <label>
        理由
        <textarea v-model="correctionReason" name="correction-reason" />
      </label>
      <p v-if="correctionError" class="customer-file__error">{{ correctionError }}</p>
      <div class="customer-file__dialog-actions">
        <button type="button" @click="correcting = null">取消</button>
        <button data-test="save-correction" type="button" @click="submitCorrection">保存修正</button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.customer-file {
  --blotter: #10263a;
  --paper: #f3f6f8;
  --brass: #9a7b4f;
  --stamp: #b42318;
  --signal: #0f766e;
  --graphite: #243140;
  --rule: color-mix(in srgb, var(--blotter) 14%, transparent);
  background: var(--paper);
  color: var(--graphite);
  padding: 28px 28px 36px;
  border: 1px solid var(--rule);
  position: relative;
}

.customer-file__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  border-bottom: 3px solid var(--blotter);
  padding-bottom: 16px;
  margin-bottom: 20px;
}

.customer-file__eyebrow {
  margin: 0;
  letter-spacing: 0.32em;
  font-size: 11px;
  font-weight: 600;
  color: var(--brass);
}

.customer-file__name {
  margin: 8px 0 0;
  font-family: "Bahnschrift", "Noto Sans SC", "Source Han Sans SC", sans-serif;
  font-size: 34px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--blotter);
}

.customer-file__date {
  margin: 0;
  padding: 8px 12px;
  border: 1px solid var(--brass);
  color: var(--blotter);
  font-size: 12px;
  letter-spacing: 0.08em;
  background: color-mix(in srgb, var(--brass) 12%, white);
}

.customer-file__warning {
  background: #fbf0dc;
  border-left: 4px solid var(--brass);
  color: #8a4b08;
  padding: 12px 16px;
  margin-bottom: 20px;
}

.customer-file__warning p {
  margin: 0 0 6px;
}

.customer-file__warning p:last-child {
  margin-bottom: 0;
}

.customer-file__break,
.customer-file__grade {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 16px;
  align-items: center;
  margin-bottom: 24px;
}

.customer-file__break {
  background: color-mix(in srgb, var(--stamp) 8%, white);
  border: 1px solid color-mix(in srgb, var(--stamp) 35%, white);
  padding: 12px 16px;
  color: var(--stamp);
}

.customer-file__break h3,
.customer-file__break p {
  margin: 0 0 6px;
}

.customer-file__stencil {
  margin: 0;
  width: 96px;
  height: 96px;
  display: grid;
  place-items: center;
  border: 4px solid var(--blotter);
  color: var(--blotter);
  font-family: "Bahnschrift", "Noto Sans SC", sans-serif;
  font-size: 36px;
  font-weight: 700;
  letter-spacing: 0.04em;
  transform: rotate(-6deg);
}

.customer-file__stencil--void {
  border-color: var(--stamp);
  color: var(--stamp);
  font-size: 22px;
  text-decoration: line-through;
}

.customer-file__grade p {
  margin: 0;
  font-size: 13px;
  letter-spacing: 0.12em;
  color: var(--signal);
}

.customer-file__grade strong {
  display: block;
  margin-top: 4px;
  font-size: 26px;
  color: var(--blotter);
}

.customer-file__allocation {
  margin-bottom: 20px;
}

.customer-file__tags {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.field-card {
  background: white;
  padding: 16px;
  border-top: 3px solid var(--blotter);
  box-shadow: 0 1px 0 var(--rule);
}

.field-card.is-low {
  border-top-color: var(--brass);
}

.field-card__meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: flex-start;
}

.field-card h3 {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.14em;
  font-weight: 600;
}

.field-card__source {
  font-size: 11px;
  color: var(--signal);
  white-space: nowrap;
}

.field-card__value {
  margin: 12px 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--blotter);
}

.field-card__confidence {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--signal);
}

.field-card__bar {
  display: block;
  height: 3px;
  margin-top: 6px;
  background: var(--signal);
}

.field-card.is-low .field-card__bar {
  background: var(--brass);
}

.field-card__correct {
  margin-top: 12px;
  background: none;
  border: 0;
  color: var(--blotter);
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
  padding: 0;
}

.customer-file__dimensions,
.customer-file__history,
.customer-file__conflicts {
  margin-top: 28px;
}

.customer-file__dimensions button {
  background: var(--blotter);
  color: var(--paper);
  border: 0;
  padding: 8px 14px;
  cursor: pointer;
}

.customer-file__dimensions ul {
  list-style: none;
  padding: 16px 0 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.customer-file__dimensions li {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-top: 2px solid var(--brass);
  padding-top: 8px;
}

.customer-file__history ol,
.customer-file__conflicts ol {
  padding-left: 22px;
}

.customer-file__history li {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr) auto;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--rule);
}

.customer-file__dialog {
  position: fixed;
  right: 32px;
  bottom: 32px;
  width: 320px;
  background: white;
  border: 1px solid var(--blotter);
  padding: 16px;
  z-index: 5;
}

.customer-file__dialog label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 10px 0;
  font-size: 13px;
}

.customer-file__dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.customer-file__error {
  color: var(--stamp);
  font-size: 13px;
}

@media (max-width: 720px) {
  .customer-file__head,
  .customer-file__break,
  .customer-file__grade,
  .customer-file__dimensions ul,
  .customer-file__history li {
    display: block;
  }

  .customer-file__date {
    margin-top: 12px;
    display: inline-block;
  }

  .customer-file__stencil {
    margin-bottom: 12px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .customer-file__stencil {
    transform: none;
  }
}
</style>
