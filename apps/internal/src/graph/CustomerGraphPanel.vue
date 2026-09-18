<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ChartFrame, toGraphOption } from "@wealth/shared";
import { errorMessage, formatDateTime, formatValue } from "../format";
import { getCustomerGraph } from "./api";
import {
  EDGE_TYPE_LABELS,
  NODE_TYPE_LABELS,
  filterAndPrune,
  toChartInput,
} from "./graphView";
import type { CustomerGraphView, GraphEdgeType, GraphNode } from "./types";

const EMPTY_HINT = "该客户暂无可展示的持仓关系。";
const ALL_EDGE_TYPES: GraphEdgeType[] = ["HOLDS", "BELONGS_TO_INDUSTRY", "MANAGED_BY"];

const props = defineProps<{ customerId: number }>();

const loading = ref(true);
const loadError = ref("");
const view = ref<CustomerGraphView | null>(null);
const activeEdgeTypes = ref<GraphEdgeType[]>([...ALL_EDGE_TYPES]);
const fundManagerExpanded = ref(false);
const selectedNode = ref<GraphNode | null>(null);

async function load(expandFundManager: boolean): Promise<void> {
  loading.value = true;
  loadError.value = "";
  selectedNode.value = null;
  try {
    view.value = await getCustomerGraph(props.customerId, { expandFundManager });
    fundManagerExpanded.value = expandFundManager;
  } catch (error) {
    view.value = null;
    loadError.value = errorMessage(error, "图谱加载失败");
  } finally {
    loading.value = false;
  }
}

// 换客户就从头开始：重置筛选与展开状态，别把上一位客户的选择带过来。
watch(
  () => props.customerId,
  () => {
    activeEdgeTypes.value = [...ALL_EDGE_TYPES];
    void load(false);
  },
  { immediate: true },
);

const option = computed(() => {
  if (!view.value) return null;
  const pruned = filterAndPrune(view.value.nodes, view.value.edges, activeEdgeTypes.value);
  const input = toChartInput(pruned.nodes, pruned.edges);
  return toGraphOption(input.nodes, input.edges, input.categories);
});

const nodesById = computed(() => {
  const map = new Map<string, GraphNode>();
  for (const node of view.value?.nodes ?? []) {
    map.set(node.id, node);
  }
  return map;
});

function onElementClick(params: unknown): void {
  const id = (params as { data?: { id?: string } }).data?.id;
  selectedNode.value = (id && nodesById.value.get(id)) || null;
}

function toggleFundManager(): void {
  void load(!fundManagerExpanded.value);
}
</script>

<template>
  <div class="graph">
    <div class="graph__controls">
      <span class="graph__label">关系类型</span>
      <el-checkbox
        v-for="type in ALL_EDGE_TYPES"
        :key="type"
        v-model="activeEdgeTypes"
        :value="type"
        :data-testid="`graph-filter-${type}`"
      >
        {{ EDGE_TYPE_LABELS[type] }}
      </el-checkbox>

      <el-button
        size="small"
        name="toggle-fund-manager"
        data-testid="graph-expand-fund-manager"
        class="graph__expand"
        @click="toggleFundManager"
      >
        {{ fundManagerExpanded ? "收起基金经理" : "展开基金经理" }}
      </el-button>
    </div>

    <p v-if="loadError" class="graph__error" role="alert" data-testid="graph-error">
      {{ loadError }}
    </p>

    <ChartFrame
      title="持仓关系图"
      hint="默认展开到产品与行业两跳，基金经理按需展开；点击节点查看要素。"
      :option="option"
      :loading="loading"
      :height="360"
      :empty-text="EMPTY_HINT"
      @element-click="onElementClick"
    />

    <div class="graph__meta">
      <span data-testid="graph-synced-at">
        {{
          view?.synced_at
            ? `图谱同步于 ${formatDateTime(view.synced_at)}`
            : "图谱尚未同步"
        }}
      </span>
    </div>

    <div v-if="selectedNode" class="graph__detail" data-testid="graph-node-detail">
      <header class="graph__detail-head">
        <strong>{{ selectedNode.label }}</strong>
        <span class="graph__detail-type">{{ NODE_TYPE_LABELS[selectedNode.type] }}</span>
        <button type="button" class="graph__close" name="close-node" @click="selectedNode = null">
          关闭
        </button>
      </header>
      <p v-if="selectedNode.marked" class="graph__marked">集中度超阈值</p>
      <dl class="graph__attrs">
        <div v-for="(value, key) in selectedNode.attrs" :key="key" class="graph__attr">
          <dt>{{ key }}</dt>
          <dd>{{ formatValue(value) }}</dd>
        </div>
      </dl>
    </div>
  </div>
</template>

<style scoped>
.graph {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-3);
}

.graph__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--wm-space-3);
}

.graph__label {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.graph__expand {
  margin-left: auto;
}

.graph__error {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.graph__meta {
  color: var(--wm-text-muted);
  font-size: 0.78rem;
}

.graph__detail {
  display: flex;
  flex-direction: column;
  gap: var(--wm-space-2);
  padding: var(--wm-space-3);
  /* 细边框属令牌纪律声明的极少数 1px 例外 */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-sm);
  background-color: var(--wm-bg-subtle);
}

.graph__detail-head {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
}

.graph__detail-type {
  color: var(--wm-text-muted);
  font-size: 0.78rem;
}

.graph__close {
  margin-left: auto;
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

.graph__marked {
  margin: 0;
  color: var(--wm-color-danger);
  font-size: 0.78rem;
}

.graph__attrs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(calc(var(--wm-space-6) * 5), 1fr));
  gap: var(--wm-space-2);
  margin: 0;
}

.graph__attr dt {
  color: var(--wm-text-muted);
  font-size: 0.75rem;
}

.graph__attr dd {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.82rem;
}
</style>
