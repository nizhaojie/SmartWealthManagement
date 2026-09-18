<script setup lang="ts">
import { computed, ref } from "vue";
import { PanelCard } from "@wealth/shared";
import { errorMessage } from "../format";
import { searchKnowledge } from "./api";
import RetrievalHitCard from "./RetrievalHitCard.vue";
import { KNOWLEDGE_TYPES, type ChunkHit, type KnowledgeType } from "./types";

/** 刚过线与勉强过线之间用 0.05 的带宽区分，远低于线用 0.1——区分的是「差多少」。 */
const NEAR_ABOVE_MARGIN = 0.05;
const FAR_BELOW_MARGIN = 0.1;

const query = ref("");
const knowledgeType = ref<KnowledgeType | "">("");
const hits = ref<ChunkHit[]>([]);
const threshold = ref(0);
const searched = ref(false);
const searching = ref(false);
const searchError = ref("");

const aboveHits = computed(() => hits.value.filter((hit) => hit.score >= threshold.value));
const belowHits = computed(() => hits.value.filter((hit) => hit.score < threshold.value));

const topScore = computed(() =>
  hits.value.length ? Math.max(...hits.value.map((hit) => hit.score)) : null,
);

const verdict = computed(() => {
  if (!searched.value) return "";
  if (topScore.value === null) return "无命中，未过兜底阈值";
  const crossed = topScore.value >= threshold.value;
  return `本次最高分 ${formatScore(topScore.value)} · ${crossed ? "已过兜底阈值" : "未过兜底阈值"}`;
});

function formatScore(score: number): string {
  return score.toFixed(3);
}

function sourceLocation(hit: ChunkHit): string {
  const heading = hit.heading_path.length ? ` · ${hit.heading_path.join(" / ")}` : "";
  return `文档 ${hit.knowledge_id} · 块 ${hit.chunk_index}${heading}`;
}

function hitPresentation(hit: ChunkHit): {
  label: string;
  tagType: "success" | "warning" | "danger" | "info";
  band: "above" | "below";
} {
  if (hit.score >= threshold.value) {
    const margin = hit.score - threshold.value;
    return margin < NEAR_ABOVE_MARGIN
      ? { label: "勉强过线", tagType: "warning", band: "above" }
      : { label: "过线", tagType: "success", band: "above" };
  }
  const gap = threshold.value - hit.score;
  return gap >= FAR_BELOW_MARGIN
    ? { label: "远低于线", tagType: "info", band: "below" }
    : { label: "低于阈值", tagType: "danger", band: "below" };
}

async function runSearch(): Promise<void> {
  searchError.value = "";
  if (!query.value.trim()) {
    searchError.value = "请输入检索问题";
    return;
  }
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
    searchError.value = errorMessage(error, "检索失败");
  } finally {
    searching.value = false;
  }
}
</script>

<template>
  <div class="lab">
    <PanelCard title="检索">
      <form class="lab__form" @submit.prevent="runSearch">
        <el-input
          v-model="query"
          name="query"
          type="textarea"
          :rows="3"
          placeholder="例如：客户风险评测过期后还能买产品吗"
        />
        <div class="lab__row">
          <label class="lab__field">
            <span class="lab__label">知识类型</span>
            <el-select v-model="knowledgeType" name="knowledge-type" placeholder="全部">
              <el-option label="全部" value="" />
              <el-option
                v-for="type in KNOWLEDGE_TYPES"
                :key="type"
                :label="type"
                :value="type"
              />
            </el-select>
          </label>
          <el-button
            type="primary"
            native-type="submit"
            name="search"
            :loading="searching"
            data-testid="search"
          >
            检索
          </el-button>
        </div>
      </form>
      <p v-if="searchError" class="lab__error" role="alert" data-testid="search-error">
        {{ searchError }}
      </p>
    </PanelCard>

    <PanelCard v-if="searched" title="检索结果">
      <p class="lab__verdict" data-testid="retrieval-verdict">{{ verdict }}</p>

      <div v-if="aboveHits.length" class="lab__hits" data-testid="hits-above">
        <RetrievalHitCard
          v-for="hit in aboveHits"
          :key="`${hit.knowledge_id}-${hit.chunk_index}`"
          :hit="hit"
          :label="hitPresentation(hit).label"
          :tag-type="hitPresentation(hit).tagType"
          :band="hitPresentation(hit).band"
          :source-location="sourceLocation(hit)"
          :score-text="formatScore(hit.score)"
        />
      </div>

      <p class="lab__threshold" data-testid="threshold-divider">
        兜底阈值 {{ formatScore(threshold) }}
      </p>

      <el-empty v-if="!hits.length" description="未命中任何知识片段" data-testid="retrieval-empty" />

      <div v-if="belowHits.length" class="lab__hits" data-testid="hits-below">
        <RetrievalHitCard
          v-for="hit in belowHits"
          :key="`${hit.knowledge_id}-${hit.chunk_index}`"
          :hit="hit"
          :label="hitPresentation(hit).label"
          :tag-type="hitPresentation(hit).tagType"
          :band="hitPresentation(hit).band"
          :source-location="sourceLocation(hit)"
          :score-text="formatScore(hit.score)"
        />
      </div>
    </PanelCard>
  </div>
</template>

<style scoped>
.lab {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-4);
}

.lab__form {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.lab__row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--wm-space-3) var(--wm-space-4);
}

.lab__field {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-1);
  min-width: calc(var(--wm-space-6) * 5);
}

.lab__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.lab__error {
  margin: var(--wm-space-3) 0 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.lab__verdict {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}

.lab__hits {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.lab__threshold {
  margin: var(--wm-space-4) 0;
  padding: var(--wm-space-2) 0;
  /* 阈值分隔线是一根 1px 细线（令牌纪律声明的极少数例外） */
  border-top: 1px dashed var(--wm-border);
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
</style>
