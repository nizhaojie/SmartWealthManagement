<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { SectionCard } from "@wealth/shared";
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

function filledAnswers(): Record<string, string> {
  return Object.fromEntries(Object.entries(answers).filter(([, value]) => value));
}

onMounted(async () => {
  try {
    const payload = await getQuestionnaire();
    questions.value = payload.questions;
    for (const question of payload.questions) {
      answers[question.id] = payload.answers[question.id] ?? "";
    }
  } catch {
    errorMessage.value = "问卷加载失败";
  } finally {
    loading.value = false;
  }
});

async function onSave() {
  saving.value = true;
  errorMessage.value = "";
  try {
    await saveDraft(filledAnswers());
  } catch {
    errorMessage.value = "保存失败";
  } finally {
    saving.value = false;
  }
}

async function onSubmit() {
  submitting.value = true;
  errorMessage.value = "";
  try {
    const result = await submitAssessment(filledAnswers());
    emit("submitted", result);
  } catch {
    errorMessage.value = "提交失败，请确认已答完全部题目";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <SectionCard title="风险测评">
    <p v-if="loading">正在加载问卷…</p>
    <p v-if="errorMessage" role="alert">{{ errorMessage }}</p>
    <form v-if="!loading" @submit.prevent="onSubmit">
      <fieldset v-for="question in questions" :key="question.id">
        <legend>{{ question.prompt }}</legend>
        <p class="dimension">{{ question.dimension }}</p>
        <label v-for="option in question.options" :key="option.id">
          <input
            type="radio"
            :name="question.id"
            :value="option.id"
            v-model="answers[question.id]"
          />
          {{ option.label }}
        </label>
      </fieldset>
      <el-button name="save" :loading="saving" @click="onSave">保存进度</el-button>
      <el-button name="submit" type="primary" native-type="submit" :loading="submitting">
        提交测评
      </el-button>
    </form>
  </SectionCard>
</template>

<style scoped>
.dimension {
  color: var(--wm-text-muted);
}
</style>
