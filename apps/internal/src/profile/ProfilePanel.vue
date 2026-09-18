<script setup lang="ts">
import { computed, ref } from "vue";
import CustomerGraphPanel from "../graph/CustomerGraphPanel.vue";
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

    <CustomerGraphPanel class="customer-file__graph" :customer-id="profile.customer_id" />

    <section class="customer-file__tags">
      <article
        v-for="tag in profile.tags"
        :key="tag.key"
        class="field-card"
        :class="{ 'is-low': tag.confidence < LOW_CONFIDENCE, 'is-expired': tag.expired }"
      >
        <div class="field-card__meta">
          <h3>{{ tag.label }}</h3>
          <span class="field-card__source">
            <span v-if="tag.expired" class="field-card__expired" data-test="tag-expired">已过期</span>
            {{ tag.source }}
          </span>
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
/*
 * 客户档案面：整页一张卡。旧的纸档配色（blotter/paper/brass/stamp/signal）
 * 全部收敛到 --wm-* 令牌：墨色→text-primary、纸面→bg-card、黄铜→warning、
 * 印章红→danger、来源青→text-muted。构成不变，只换皮。
 *
 * 偏离声明：本页是 04 号 ticket「内容包进 PanelCard」纪律下的唯一例外——
 * 档案头（眉标/姓名/日期戳）与印章/熔断构成不适配 PanelCard 的标题栏插槽，
 * 硬套等于重排信息架构；故按 spec「复合组件：页面级独有模式留在各自应用」
 * 在应用内复刻 PanelCard 的容器配方（白面/边线/圆角/阴影/间距），
 * 视觉与其余页面的卡片保持同一语言。
 */
.customer-file {
  background: var(--wm-bg-card);
  color: var(--wm-text-secondary);
  padding: var(--wm-space-5);
  /* 档案卡 1px 边线（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-lg);
  box-shadow: var(--wm-shadow-card);
  position: relative;
}

.customer-file__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--wm-space-4);
  /* 档头 3px 墨线：档案「装订线」，保留厚度（非 1px 细线例外） */
  border-bottom: 3px solid var(--wm-text-primary);
  padding-bottom: var(--wm-space-4);
  margin-bottom: var(--wm-space-4);
}

.customer-file__eyebrow {
  margin: 0;
  letter-spacing: 0.32em;
  font-size: 11px;
  font-weight: 600;
  color: var(--wm-text-muted);
}

.customer-file__name {
  margin: var(--wm-space-2) 0 0;
  font-size: 34px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--wm-text-primary);
}

.customer-file__date {
  margin: 0;
  padding: var(--wm-space-2) var(--wm-space-3);
  /* 日期戳 1px 边线（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border-hairline);
  border-radius: var(--wm-radius-sm);
  color: var(--wm-text-muted);
  font-size: 12px;
  letter-spacing: 0.08em;
  background: var(--wm-bg-page);
}

.customer-file__warning {
  background: color-mix(in srgb, var(--wm-color-warning) 8%, var(--wm-bg-card));
  /* 4px warning 左条：警示条规格，同 StatCard 左条家族（非 1px 细线例外） */
  border-left: 4px solid var(--wm-color-warning);
  color: var(--wm-color-warning);
  padding: var(--wm-space-3) var(--wm-space-4);
  margin-bottom: var(--wm-space-4);
}

.customer-file__warning p {
  margin: 0 0 var(--wm-space-1);
}

.customer-file__warning p:last-child {
  margin-bottom: 0;
}

.customer-file__break,
.customer-file__grade {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: var(--wm-space-4);
  align-items: center;
  margin-bottom: var(--wm-space-5);
}

.customer-file__break {
  background: color-mix(in srgb, var(--wm-color-danger) 8%, var(--wm-bg-card));
  border: 1px solid color-mix(in srgb, var(--wm-color-danger) 35%, var(--wm-bg-card));
  border-radius: var(--wm-radius-md);
  padding: var(--wm-space-3) var(--wm-space-4);
  color: var(--wm-color-danger);
}

.customer-file__break h3,
.customer-file__break p {
  margin: 0 0 var(--wm-space-1);
}

.customer-file__stencil {
  margin: 0;
  width: 96px;
  height: 96px;
  display: grid;
  place-items: center;
  /* 4px 印章描边：仿印章粗边，保留厚度（非 1px 细线例外） */
  border: 4px solid var(--wm-text-primary);
  border-radius: var(--wm-radius-sm);
  color: var(--wm-text-primary);
  font-size: 36px;
  font-weight: 700;
  letter-spacing: 0.04em;
  transform: rotate(-6deg);
}

.customer-file__stencil--void {
  border-color: var(--wm-color-danger);
  color: var(--wm-color-danger);
  font-size: 22px;
  text-decoration: line-through;
}

.customer-file__grade p {
  margin: 0;
  font-size: 13px;
  letter-spacing: 0.12em;
  color: var(--wm-text-muted);
}

.customer-file__grade strong {
  display: block;
  margin-top: var(--wm-space-1);
  font-size: 26px;
  color: var(--wm-text-primary);
}

.customer-file__allocation {
  margin-bottom: var(--wm-space-4);
}

.customer-file__tags {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--wm-space-4);
}

/* 白卡上的字段瓦片：页面底色反衬 + 发丝线勾边 */
.field-card {
  background: var(--wm-bg-page);
  padding: var(--wm-space-4);
  border: 1px solid var(--wm-border-hairline);
  border-top: 3px solid var(--wm-text-primary);
  border-radius: var(--wm-radius-sm);
}

.field-card.is-low {
  border-top-color: var(--wm-color-warning);
}

.field-card.is-expired {
  border-top-color: var(--wm-color-danger);
}

.field-card__meta {
  display: flex;
  justify-content: space-between;
  gap: var(--wm-space-2);
  align-items: flex-start;
}

.field-card h3 {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.14em;
  font-weight: 600;
  color: var(--wm-text-primary);
}

.field-card__source {
  font-size: 11px;
  color: var(--wm-text-muted);
  white-space: nowrap;
}

.field-card__expired {
  color: var(--wm-color-danger);
  border: 1px solid currentColor;
  padding: 0 var(--wm-space-1);
  margin-right: var(--wm-space-1);
  font-size: 10px;
}

.field-card__value {
  margin: var(--wm-space-3) 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--wm-text-primary);
}

.field-card__confidence {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--wm-text-muted);
}

.field-card__bar {
  display: block;
  height: 3px;
  margin-top: var(--wm-space-1);
  background: var(--wm-text-muted);
}

.field-card.is-low .field-card__bar {
  background: var(--wm-color-warning);
}

.field-card__correct {
  margin-top: var(--wm-space-3);
  background: none;
  border: 0;
  color: var(--wm-color-primary);
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
  padding: 0;
}

.customer-file__dimensions,
.customer-file__history,
.customer-file__conflicts {
  margin-top: var(--wm-space-5);
}

.customer-file__dimensions button {
  background: var(--wm-color-primary);
  color: var(--wm-bg-card);
  border: 0;
  border-radius: var(--wm-radius-sm);
  padding: var(--wm-space-2) var(--wm-space-3);
  cursor: pointer;
}

.customer-file__dimensions ul {
  list-style: none;
  padding: var(--wm-space-4) 0 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--wm-space-3);
}

.customer-file__dimensions li {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  /* 2px 黄铜顶线：维度刻度标记，保留厚度（非 1px 细线例外） */
  border-top: 2px solid var(--wm-color-warning);
  padding-top: var(--wm-space-2);
  color: var(--wm-text-primary);
}

.customer-file__history ol,
.customer-file__conflicts ol {
  padding-left: var(--wm-space-5);
}

.customer-file__history li {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr) auto;
  gap: var(--wm-space-3);
  padding: var(--wm-space-2) 0;
  /* 历次记录的 1px 虚线分隔（令牌纪律声明的极少数例外） */
  border-bottom: 1px dashed var(--wm-border-hairline);
}

.customer-file__dialog {
  position: fixed;
  right: var(--wm-space-6);
  bottom: var(--wm-space-6);
  width: 320px;
  background: var(--wm-bg-card);
  /* 修正浮层 1px 边线（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-md);
  box-shadow: var(--wm-shadow-overlay);
  padding: var(--wm-space-4);
  z-index: 5;
}

.customer-file__dialog label {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  margin: var(--wm-space-2) 0;
  font-size: 13px;
  color: var(--wm-text-primary);
}

.customer-file__dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--wm-space-2);
}

.customer-file__error {
  color: var(--wm-color-danger);
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
    margin-top: var(--wm-space-3);
    display: inline-block;
  }

  .customer-file__stencil {
    margin-bottom: var(--wm-space-3);
  }
}

@media (prefers-reduced-motion: reduce) {
  .customer-file__stencil {
    transform: none;
  }
}
</style>
