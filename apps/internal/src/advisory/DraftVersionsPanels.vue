<script setup lang="ts">
import { computed } from "vue";
import { PanelCard } from "@wealth/shared";
import type { AdvisoryDraft, AdvisoryFinal, EditableCandidate } from "./types";

/**
 * 两版本并排：左列永远是 AI 原稿（永久留存，用于举证审核是否为实质性审核），
 * 右列在放行前是顾问编辑版本、放行后换成顾问定稿（唯一允许送达客户的版本）。
 *
 * 编辑版本上的勾选与配置调整直接写在传入的 `candidates` / `allocation` 上——
 * 这两份状态由页面持有，组件只是它的编辑面。
 */
const props = defineProps<{
  draft: AdvisoryDraft;
  final: AdvisoryFinal | null;
  candidates: EditableCandidate[];
  allocation: Record<string, number>;
  editable: boolean;
}>();

const removedCount = computed(() => props.candidates.filter((item) => !item.included).length);
</script>

<template>
  <div class="versions">
    <PanelCard title="AI 原稿" data-testid="original-panel">
      <el-table :data="draft.candidates" row-key="product_code">
        <el-table-column type="expand">
          <template #default="{ row }">
            <ul class="breakdown" data-testid="score-breakdown">
              <li v-for="item in row.score_breakdown" :key="item.dimension">
                {{ item.dimension }}：{{ item.raw_value }}，得分 {{ item.score }} × 权重
                {{ item.weight }} = 贡献 {{ item.contribution }}
              </li>
            </ul>
          </template>
        </el-table-column>
        <el-table-column label="产品" prop="product_name" min-width="160" />
        <el-table-column label="风险等级" prop="risk_level" width="100" />
        <el-table-column label="综合得分" prop="composite_score" width="110" />
      </el-table>

      <div class="allocation">
        <h4 class="allocation__title">配置建议</h4>
        <p v-for="(value, key) in draft.allocation_suggestion" :key="key" class="allocation__row">
          {{ key }}：{{ value }}%
        </p>
      </div>
    </PanelCard>

    <PanelCard v-if="final" title="顾问定稿" data-testid="final-panel">
      <p class="versions__release">
        放行人：{{ final.advisor_name ?? "—" }} · {{ final.released_at }}
      </p>
      <el-table :data="final.candidates" row-key="product_code">
        <el-table-column label="产品" prop="product_name" min-width="160" />
        <el-table-column label="风险等级" prop="risk_level" width="100" />
        <el-table-column label="综合得分" prop="composite_score" width="110" />
      </el-table>

      <div class="allocation">
        <h4 class="allocation__title">配置建议</h4>
        <p v-for="(value, key) in final.allocation_suggestion" :key="key" class="allocation__row">
          {{ key }}：{{ value }}%
        </p>
      </div>
    </PanelCard>

    <PanelCard v-else title="顾问编辑版本" data-testid="edited-panel">
      <p v-if="removedCount" class="versions__removed" data-testid="removed-note">
        已从原稿移除 {{ removedCount }} 项推荐产品
      </p>

      <el-table :data="candidates" row-key="product_code">
        <el-table-column type="expand">
          <template #default="{ row }">
            <ul class="breakdown" data-testid="score-breakdown-edited">
              <li v-for="item in row.score_breakdown" :key="item.dimension">
                {{ item.dimension }}：{{ item.raw_value }}，得分 {{ item.score }} × 权重
                {{ item.weight }} = 贡献 {{ item.contribution }}
              </li>
            </ul>
          </template>
        </el-table-column>
        <el-table-column label="保留" width="80">
          <template #default="{ row }">
            <el-checkbox
              v-model="row.included"
              :disabled="!editable"
              data-testid="candidate-include"
            />
          </template>
        </el-table-column>
        <el-table-column label="产品" min-width="160">
          <template #default="{ row }">
            <span :class="{ 'versions__dropped': !row.included }">{{ row.product_name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="风险等级" prop="risk_level" width="100" />
        <el-table-column label="综合得分" prop="composite_score" width="110" />
      </el-table>

      <div class="allocation">
        <h4 class="allocation__title">配置建议</h4>
        <div v-for="(value, key) in allocation" :key="key" class="allocation__edit">
          <span class="allocation__key">{{ key }}</span>
          <el-input-number
            v-model="allocation[key]"
            :min="0"
            :max="100"
            :disabled="!editable"
            size="small"
            data-testid="allocation-input"
          />
          <span
            v-if="value !== draft.allocation_suggestion[key]"
            class="allocation__changed"
            data-testid="allocation-changed"
          >
            （原 {{ draft.allocation_suggestion[key] }}%）
          </span>
        </div>
      </div>
    </PanelCard>
  </div>
</template>

<style scoped>
.versions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--wm-space-4);
  align-items: start;
}

@media (max-width: 1280px) {
  .versions {
    grid-template-columns: minmax(0, 1fr);
  }
}

.breakdown {
  margin: 0;
  padding-left: var(--wm-space-4);
  color: var(--wm-text-muted);
  font-size: 0.78rem;
  line-height: 1.8;
}

.allocation {
  margin-top: var(--wm-space-4);
}

.allocation__title {
  margin: 0 0 var(--wm-space-2);
  color: var(--wm-text-primary);
  font-size: 0.85rem;
  font-weight: 600;
}

.allocation__row {
  margin: 0 0 var(--wm-space-1);
  color: var(--wm-text-muted);
  font-size: 0.82rem;
  font-variant-numeric: tabular-nums;
}

.allocation__edit {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
  margin-bottom: var(--wm-space-2);
}

.allocation__key {
  min-width: calc(var(--wm-space-6) * 2);
  color: var(--wm-text-muted);
  font-size: 0.82rem;
}

.allocation__changed {
  color: var(--wm-color-warning);
  font-size: 0.78rem;
  font-variant-numeric: tabular-nums;
}

.versions__removed {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-color-warning);
  font-size: 0.82rem;
}

.versions__dropped {
  color: var(--wm-text-muted);
  text-decoration: line-through;
}

.versions__release {
  margin: 0 0 var(--wm-space-3);
  color: var(--wm-text-muted);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}
</style>
