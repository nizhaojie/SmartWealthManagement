<script setup lang="ts">
import { computed, ref } from "vue";
import type { CustomerProfileView, ProfileTag } from "./types";

const props = defineProps<{ profile: CustomerProfileView }>();
const emit = defineEmits<{
  correct: [payload: { tagKey: string; value: unknown; reason: string }];
}>();

const GRADE_LABELS: Record<string, string> = {
  C1: "保守型",
  C2: "稳健型",
  C3: "平衡型",
  C4: "进取型",
  C5: "激进型",
};

const DIMENSION_ORDER = ["基础属性", "投资经验", "风险偏好", "行为异常"] as const;

const showDimensions = ref(false);
const correcting = ref<ProfileTag | null>(null);
const correctionValue = ref("");
const correctionReason = ref("");
const correctionError = ref("");

const computedAtLabel = computed(() => props.profile.computed_at.slice(0, 10));

const judgementGrade = computed(() => {
  const level = props.profile.judgement.risk_level;
  if (!level) return null;
  return `${level} ${GRADE_LABELS[level] ?? ""}`.trim();
});

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function formatConfidence(value: number): string {
  return value.toFixed(2);
}

function openCorrection(tag: ProfileTag) {
  correcting.value = tag;
  correctionValue.value = typeof tag.value === "string" ? tag.value : formatValue(tag.value);
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
    value: correctionValue.value,
    reason,
  });
  correcting.value = null;
}
</script>

<template>
  <article class="dossier">
    <header class="dossier__head">
      <div>
        <p class="dossier__eyebrow">客户画像</p>
        <h2 class="dossier__name">{{ profile.real_name }}</h2>
      </div>
      <p class="dossier__stamp" data-test="computed-at">计算于 {{ computedAtLabel }}</p>
    </header>

    <section
      v-if="profile.judgement.circuit_break"
      class="dossier__break"
      data-test="circuit-break"
    >
      <h3>硬性门槛已熔断</h3>
      <p v-for="reason in profile.judgement.reasons" :key="reason.code">{{ reason.message }}</p>
    </section>

    <p v-else class="dossier__grade">
      四维度研判
      <strong>{{ judgementGrade }}</strong>
    </p>

    <section class="dossier__tags">
      <article v-for="tag in profile.tags" :key="tag.key" class="tag-card">
        <div class="tag-card__meta">
          <h3>{{ tag.label }}</h3>
          <span class="tag-card__source">{{ tag.source }}</span>
        </div>
        <p class="tag-card__value">{{ formatValue(tag.value) }}</p>
        <div class="tag-card__confidence">
          <span>置信度 {{ formatConfidence(tag.confidence) }}</span>
          <i class="tag-card__bar" :style="{ width: `${Math.round(tag.confidence * 100)}%` }" />
        </div>
        <button class="tag-card__correct" type="button" @click="openCorrection(tag)">修正</button>
      </article>
    </section>

    <section v-if="profile.judgement.dimension_scores" class="dossier__dimensions">
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

    <section v-if="profile.conflict_records.length" class="dossier__conflicts">
      <h3>冲突记录</h3>
      <ol>
        <li v-for="(record, index) in profile.conflict_records" :key="`${record.tag_key}-${index}`">
          {{ record.changed_at.slice(0, 10) }}
          · {{ record.old_source }} 的「{{ formatValue(record.old_value) }}」
          被 {{ record.new_source }} 改为「{{ formatValue(record.new_value) }}」
        </li>
      </ol>
    </section>

    <div v-if="correcting" class="dossier__dialog">
      <h3>修正 {{ correcting.label }}</h3>
      <label>
        新值
        <input v-model="correctionValue" name="correction-value" />
      </label>
      <label>
        理由
        <textarea v-model="correctionReason" name="correction-reason" />
      </label>
      <p v-if="correctionError" class="dossier__error">{{ correctionError }}</p>
      <div class="dossier__dialog-actions">
        <button type="button" @click="correcting = null">取消</button>
        <button type="button" @click="submitCorrection">保存修正</button>
      </div>
    </div>
  </article>
</template>

<style scoped>
.dossier {
  --ink: #1b2a4a;
  --vellum: #f7f4ec;
  --seal: #9b2c2c;
  --teal: #2a6f6f;
  --gold: #c4a35a;
  --graphite: #3d3a37;
  background: var(--vellum);
  color: var(--graphite);
  padding: 28px;
  border: 1px solid color-mix(in srgb, var(--ink) 18%, transparent);
  box-shadow: inset 0 0 0 1px #fff8e8;
}

.dossier__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  border-bottom: 1px solid var(--gold);
  padding-bottom: 16px;
  margin-bottom: 20px;
}

.dossier__eyebrow {
  margin: 0;
  letter-spacing: 0.28em;
  font-size: 11px;
  text-transform: uppercase;
  color: var(--teal);
}

.dossier__name {
  margin: 6px 0 0;
  font-family: "Noto Serif SC", "Songti SC", "STSong", serif;
  font-size: 32px;
  color: var(--ink);
  font-weight: 600;
}

.dossier__stamp {
  margin: 0;
  padding: 8px 10px;
  border: 2px solid var(--teal);
  color: var(--teal);
  font-size: 12px;
  transform: rotate(-2deg);
}

.dossier__break {
  background: color-mix(in srgb, var(--seal) 10%, white);
  border-left: 4px solid var(--seal);
  padding: 16px 18px;
  margin-bottom: 24px;
  color: var(--seal);
}

.dossier__break h3,
.dossier__break p {
  margin: 0 0 8px;
}

.dossier__grade {
  font-size: 15px;
  margin: 0 0 20px;
}

.dossier__grade strong {
  margin-left: 8px;
  font-family: "Noto Serif SC", "Songti SC", serif;
  font-size: 22px;
  color: var(--ink);
}

.dossier__tags {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.tag-card {
  background: #fffdf7;
  padding: 16px;
  border: 1px solid color-mix(in srgb, var(--ink) 12%, transparent);
  position: relative;
}

.tag-card__meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: flex-start;
}

.tag-card h3 {
  margin: 0;
  font-size: 13px;
  letter-spacing: 0.08em;
}

.tag-card__source {
  border: 1px solid var(--gold);
  color: var(--ink);
  font-size: 11px;
  padding: 2px 6px;
  white-space: nowrap;
}

.tag-card__value {
  margin: 12px 0;
  font-family: "Noto Serif SC", "Songti SC", serif;
  font-size: 20px;
  color: var(--ink);
}

.tag-card__confidence {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--teal);
}

.tag-card__bar {
  display: block;
  height: 3px;
  margin-top: 6px;
  background: linear-gradient(90deg, var(--teal), color-mix(in srgb, var(--teal) 20%, white));
}

.tag-card__correct {
  margin-top: 12px;
  background: none;
  border: 0;
  color: var(--ink);
  text-decoration: underline;
  cursor: pointer;
  padding: 0;
}

.dossier__dimensions {
  margin-top: 28px;
}

.dossier__dimensions button {
  background: var(--ink);
  color: var(--vellum);
  border: 0;
  padding: 8px 14px;
  cursor: pointer;
}

.dossier__dimensions ul {
  list-style: none;
  padding: 16px 0 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.dossier__dimensions li {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-top: 2px solid var(--gold);
  padding-top: 8px;
}

.dossier__conflicts {
  margin-top: 28px;
}

.dossier__conflicts ol {
  padding-left: 18px;
}

.dossier__dialog {
  position: fixed;
  right: 32px;
  bottom: 32px;
  width: 320px;
  background: #fffdf7;
  border: 1px solid var(--ink);
  padding: 16px;
  z-index: 5;
}

.dossier__dialog label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 10px 0;
  font-size: 13px;
}

.dossier__dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.dossier__error {
  color: var(--seal);
  font-size: 13px;
}

@media (max-width: 720px) {
  .dossier__head,
  .dossier__dimensions ul {
    display: block;
  }

  .dossier__stamp {
    margin-top: 12px;
    display: inline-block;
  }
}
</style>
