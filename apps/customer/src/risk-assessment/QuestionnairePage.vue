<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ApiError, MeterBar, PanelCard } from "@wealth/shared";
import { getQuestionnaire, saveDraft, submitAssessment } from "./api";
import type { AssessmentResult, Question } from "./types";

const emit = defineEmits<{
  submitted: [result: AssessmentResult];
}>();

const questions = ref<Question[]>([]);
const answers = reactive<Record<string, string>>({});
const loading = ref(true);
const saving = ref(false);
const submitting = ref(false);
const errorMessage = ref("");
const notice = ref("");

const answeredCount = computed(() => questions.value.filter((item) => answers[item.id]).length);
const progressPercent = computed(() =>
  questions.value.length === 0
    ? 0
    : Math.round((answeredCount.value / questions.value.length) * 100),
);

function filledAnswers(): Record<string, string> {
  return Object.fromEntries(Object.entries(answers).filter(([, value]) => value));
}

function failureText(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

onMounted(async () => {
  try {
    const payload = await getQuestionnaire();
    questions.value = payload.questions;
    for (const question of payload.questions) {
      answers[question.id] = payload.answers[question.id] ?? "";
    }
  } catch (error) {
    errorMessage.value = failureText(error, "问卷加载失败，请稍后重试");
  } finally {
    loading.value = false;
  }
});

async function onSave(): Promise<void> {
  saving.value = true;
  errorMessage.value = "";
  notice.value = "";
  try {
    await saveDraft(filledAnswers());
    notice.value = "进度已保存，下次进入可以接着答。";
  } catch (error) {
    errorMessage.value = failureText(error, "保存失败，请稍后重试");
  } finally {
    saving.value = false;
  }
}

async function onSubmit(): Promise<void> {
  errorMessage.value = "";
  notice.value = "";
  if (answeredCount.value < questions.value.length) {
    errorMessage.value = "请完成全部题目后再提交";
    return;
  }

  submitting.value = true;
  try {
    emit("submitted", await submitAssessment(filledAnswers()));
  } catch (error) {
    errorMessage.value = failureText(error, "提交失败，请稍后重试");
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <PanelCard title="风险测评问卷">
    <p v-if="loading" class="questionnaire__status">正在加载问卷…</p>

    <template v-else>
      <div class="questionnaire__progress">
        <MeterBar :label="`已答 ${answeredCount} / ${questions.length} 题`" :percent="progressPercent" />
      </div>

      <p v-if="errorMessage" class="questionnaire__error" role="alert" data-testid="questionnaire-error">
        {{ errorMessage }}
      </p>
      <p v-if="notice" class="questionnaire__notice" role="status" data-testid="questionnaire-notice">
        {{ notice }}
      </p>

      <form class="questionnaire__form" @submit.prevent="onSubmit">
        <fieldset v-for="(question, index) in questions" :key="question.id" class="question">
          <legend class="question__legend">
            <span class="question__index">{{ index + 1 }}</span>
            <span class="question__prompt">{{ question.prompt }}</span>
            <span class="question__dimension">{{ question.dimension }}</span>
          </legend>
          <el-radio-group v-model="answers[question.id]" class="question__options">
            <el-radio
              v-for="option in question.options"
              :key="option.id"
              :value="option.id"
              :name="question.id"
            >
              {{ option.label }}
            </el-radio>
          </el-radio-group>
        </fieldset>

        <div class="questionnaire__actions">
          <el-button name="save" :loading="saving" @click="onSave">保存进度</el-button>
          <el-button name="submit" type="primary" native-type="submit" :loading="submitting">
            提交测评
          </el-button>
        </div>
      </form>
    </template>
  </PanelCard>
</template>

<style scoped>
.questionnaire__status {
  margin: 0;
  color: var(--wm-text-muted);
}

.questionnaire__progress {
  margin-bottom: var(--wm-space-5);
}

.questionnaire__error {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.questionnaire__notice {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-color-success);
  font-size: 0.85rem;
}

.questionnaire__form {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-5);
}

/* 题目块自身不带边框：02 的层级靠间距与字号，不靠给每一行加框 */
.question {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  margin: 0;
  padding: 0;
  border: none;
}

.question__legend {
  display: flex;
  align-items: baseline;
  gap: var(--wm-space-2);
  padding: 0;
}

.question__index {
  display: inline-grid;
  place-items: center;
  width: var(--wm-space-5);
  height: var(--wm-space-5);
  border-radius: var(--wm-radius-pill);
  background-color: var(--wm-color-primary-tint);
  color: var(--wm-color-primary-strong);
  font-size: 0.75rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.question__prompt {
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  font-weight: 600;
}

.question__dimension {
  color: var(--wm-text-muted);
  font-size: 0.75rem;
}

.question__options {
  display: flex;
  flex-wrap: wrap;
  gap: var(--wm-space-2) var(--wm-space-5);
  padding-left: var(--wm-space-5);
}

.questionnaire__actions {
  display: flex;
  gap: var(--wm-space-3);
}
</style>
