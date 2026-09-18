<script setup lang="ts">
import { computed, ref } from "vue";
import { PanelCard } from "@wealth/shared";
import { searchKnowledge } from "./api";
import RetrievalHitCard from "./RetrievalHitCard.vue";
import { KNOWLEDGE_TYPES, type ChunkHit, type KnowledgeType } from "./types";

const NEAR_ABOVE_MARGIN = 0.05;
const FAR_BELOW_MARGIN = 0.1;

const query = ref("");
const knowledgeType = ref<KnowledgeType | "">("");
const hits = ref<ChunkHit[]>([]);
const threshold = ref(0);
const searched = ref(false);
const searching = ref(false);
const searchError = ref("");

const aboveHits = computed(() => hits.value.filter((hit) => hit.score >= threshold.value).map(decorateHit));
const belowHits = computed(() => hits.value.filter((hit) => hit.score < threshold.value).map(decorateHit));

const verdict = computed(() => {
  if (!searched.value) {
    return "";
  }
  if (hits.value.length === 0) {
    return "无命中，未过兜底阈值";
  }
  const topScore = Math.max(...hits.value.map((hit) => hit.score));
  const crossed = topScore >= threshold.value;
  return `本次最高分 ${formatScore(topScore)} · ${crossed ? "已过兜底阈值" : "未过兜底阈值"}`;
});

async function onSearch() {
  searchError.value = "";
  searching.value = true;
  try {
    const result = await searchKnowledge({
      query: query.value,
      knowledgeType: knowledgeType.value || undefined,
    });
    hits.value = result.hits;
    threshold.value = result.score_threshold;
    searched.value = true;
  } catch (error) {
    searchError.value = error instanceof Error ? error.message : "检索失败";
  } finally {
    searching.value = false;
  }
}

function decorateHit(hit: ChunkHit) {
  const presentation = hitPresentation(hit);
  return {
    hit,
    ...presentation,
    sourceLocation: sourceLocation(hit),
    scoreText: formatScore(hit.score),
  };
}

function sourceLocation(hit: ChunkHit): string {
  const parts = [`文档 ${hit.knowledge_id}`, `块 ${hit.chunk_index}`];
  if (hit.heading_path.length > 0) {
    parts.push(hit.heading_path.join(" / "));
  }
  return parts.join(" · ");
}

function formatScore(score: number): string {
  return score.toFixed(2);
}

function hitPresentation(hit: ChunkHit): {
  label: string;
  tagType: "success" | "warning" | "danger" | "info";
  band: "above" | "below";
} {
  if (hit.score >= threshold.value) {
    const barely = hit.score - threshold.value < NEAR_ABOVE_MARGIN;
    return {
      label: barely ? "勉强过线" : "过线",
      tagType: barely ? "warning" : "success",
      band: "above",
    };
  }
  const farBelow = threshold.value - hit.score >= FAR_BELOW_MARGIN;
  return {
    label: farBelow ? "远低于线" : "低于阈值",
    tagType: farBelow ? "info" : "danger",
    band: "below",
  };
}
</script>

<template>
  <PanelCard title="检索试验">
    <div class="retrieval-lab__form">
      <el-input
        v-model="query"
        type="textarea"
        name="query"
        :rows="3"
        placeholder="输入一个问题，直接看检索命中，不必绕道对话"
      />
      <el-select v-model="knowledgeType" placeholder="按知识类型限定" clearable style="width: 160px">
        <el-option v-for="type in KNOWLEDGE_TYPES" :key="type" :label="type" :value="type" />
      </el-select>
      <el-button name="search" type="primary" :loading="searching" @click="onSearch">检索</el-button>
    </div>
    <p v-if="searchError" role="alert" class="retrieval-lab__error">{{ searchError }}</p>
    <p v-if="verdict" class="retrieval-lab__verdict">{{ verdict }}</p>
    <template v-if="searched">
      <RetrievalHitCard
        v-for="row in aboveHits"
        :key="`${row.hit.knowledge_id}-${row.hit.chunk_index}`"
        :hit="row.hit"
        :band="row.band"
        :label="row.label"
        :tag-type="row.tagType"
        :source-location="row.sourceLocation"
        :score-text="row.scoreText"
      />
      <div class="retrieval-lab__threshold">兜底阈值 {{ formatScore(threshold) }}</div>
      <el-empty v-if="hits.length === 0" description="未命中任何知识片段" />
      <RetrievalHitCard
        v-for="row in belowHits"
        :key="`${row.hit.knowledge_id}-${row.hit.chunk_index}`"
        :hit="row.hit"
        :band="row.band"
        :label="row.label"
        :tag-type="row.tagType"
        :source-location="row.sourceLocation"
        :score-text="row.scoreText"
      />
    </template>
  </PanelCard>
</template>

<style scoped>
.retrieval-lab__form {
  display: flex;
  align-items: flex-start;
  gap: var(--wm-space-3);
  margin-bottom: var(--wm-space-4);
}

.retrieval-lab__form :deep(.el-textarea) {
  flex: 1;
}

.retrieval-lab__error {
  color: var(--wm-color-danger);
}

.retrieval-lab__verdict {
  margin: 0 0 var(--wm-space-3);
  font-weight: 600;
  color: var(--wm-text-primary);
}

/* 阈值分隔线是装饰性虚线（2px dashed），不属于 1px 细线例外，特意保留厚度 */
.retrieval-lab__threshold {
  margin: var(--wm-space-4) 0;
  padding: var(--wm-space-2) 0;
  border-top: 2px dashed var(--wm-color-warning);
  color: var(--wm-color-warning);
  font-weight: 600;
  text-align: center;
}
</style>
