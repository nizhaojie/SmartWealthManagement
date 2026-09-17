<script setup lang="ts">
import { ChartFrame, toGraphOption } from "@wealth/shared";
import { computed, onMounted, ref, watch } from "vue";
import { getCustomerGraph } from "./api";
import { EDGE_TYPE_LABELS, NODE_TYPE_LABELS, filterAndPrune, toChartInput } from "./graphView";
import type { CustomerGraphView, GraphEdgeType, GraphNode } from "./types";

const EMPTY_HINT = "该客户暂无可展示的持仓关系。";
const ALL_EDGE_TYPES: GraphEdgeType[] = ["HOLDS", "BELONGS_TO_INDUSTRY", "MANAGED_BY"];

const props = defineProps<{
  customerId: number;
}>();

const loading = ref(true);
const loadError = ref("");
const view = ref<CustomerGraphView | null>(null);
const activeEdgeTypes = ref<GraphEdgeType[]>([...ALL_EDGE_TYPES]);
const fundManagerExpanded = ref(false);
const selectedNode = ref<GraphNode | null>(null);

async function load(expandFundManager: boolean) {
  loading.value = true;
  loadError.value = "";
  try {
    view.value = await getCustomerGraph(props.customerId, { expandFundManager });
  } catch {
    loadError.value = "图谱数据加载失败，请稍后重试";
  } finally {
    loading.value = false;
  }
}

onMounted(() => load(fundManagerExpanded.value));

watch(
  () => props.customerId,
  () => {
    fundManagerExpanded.value = false;
    selectedNode.value = null;
    void load(false);
  },
);

function toggleFundManagers() {
  fundManagerExpanded.value = !fundManagerExpanded.value;
  selectedNode.value = null;
  void load(fundManagerExpanded.value);
}

function toggleEdgeType(type: GraphEdgeType) {
  activeEdgeTypes.value = activeEdgeTypes.value.includes(type)
    ? activeEdgeTypes.value.filter((item) => item !== type)
    : [...activeEdgeTypes.value, type];
}

const filtered = computed(() => {
  if (!view.value) return { nodes: [], edges: [] };
  return filterAndPrune(view.value.nodes, view.value.edges, activeEdgeTypes.value);
});

const option = computed(() => {
  const input = toChartInput(filtered.value.nodes, filtered.value.edges);
  return toGraphOption(input.nodes, input.edges, input.categories);
});

const syncedAtLabel = computed(() => {
  const value = view.value?.synced_at;
  return value ? `图谱同步于 ${value.slice(0, 16).replace("T", " ")}` : "图谱尚未同步";
});

function onElementClick(params: unknown) {
  const clicked = params as { dataType?: string; data?: { id?: string } } | null;
  if (clicked?.dataType !== "node" || !clicked.data?.id || !view.value) return;
  selectedNode.value = view.value.nodes.find((node) => node.id === clicked.data?.id) ?? null;
}

function attrEntries(node: GraphNode): [string, string][] {
  return Object.entries(node.attrs).map(([key, value]) => [key, String(value)]);
}
</script>

<template>
  <section class="customer-graph" data-test="customer-graph-panel">
    <header class="customer-graph__head">
      <h3>持仓关系网络</h3>
      <p class="customer-graph__synced" data-test="graph-synced-at">{{ syncedAtLabel }}</p>
    </header>

    <p v-if="loadError" class="customer-graph__error" data-test="graph-error">{{ loadError }}</p>

    <template v-else>
      <div class="customer-graph__controls">
        <label
          v-for="type in ALL_EDGE_TYPES"
          :key="type"
          class="customer-graph__filter"
        >
          <input
            type="checkbox"
            :checked="activeEdgeTypes.includes(type)"
            :data-test="`graph-filter-${type}`"
            @change="toggleEdgeType(type)"
          />
          {{ EDGE_TYPE_LABELS[type] }}
        </label>
        <button type="button" data-test="graph-expand-fund-manager" @click="toggleFundManagers">
          {{ fundManagerExpanded ? "收起基金经理" : "展开基金经理" }}
        </button>
      </div>

      <ChartFrame
        title="客户持仓关系图"
        hint="默认展开到产品与行业两跳，基金经理按需展开；点击节点查看要素。"
        :option="option"
        :loading="loading"
        :empty-text="EMPTY_HINT"
        :height="360"
        @element-click="onElementClick"
      />

      <aside v-if="selectedNode" class="customer-graph__detail" data-test="graph-node-detail">
        <div class="customer-graph__detail-head">
          <h4>{{ selectedNode.label }}</h4>
          <span>{{ NODE_TYPE_LABELS[selectedNode.type] }}</span>
          <button type="button" @click="selectedNode = null">关闭</button>
        </div>
        <p v-if="selectedNode.marked" class="customer-graph__marked">集中度超阈值</p>
        <dl>
          <template v-for="[key, value] in attrEntries(selectedNode)" :key="key">
            <dt>{{ key }}</dt>
            <dd>{{ value }}</dd>
          </template>
        </dl>
      </aside>
    </template>
  </section>
</template>

<style scoped>
.customer-graph {
  margin-bottom: var(--wm-space-4);
}

.customer-graph__head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--wm-space-2);
}

.customer-graph__head h3 {
  margin: 0;
  font-size: 1rem;
  color: var(--wm-text-primary);
}

.customer-graph__synced {
  margin: 0;
  font-size: 0.8rem;
  color: var(--wm-text-muted);
}

.customer-graph__error {
  color: var(--wm-color-danger);
}

.customer-graph__controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--wm-space-3);
  align-items: center;
  margin-bottom: var(--wm-space-2);
  font-size: 0.85rem;
  color: var(--wm-text-secondary);
}

.customer-graph__filter {
  display: inline-flex;
  align-items: center;
  gap: var(--wm-space-1);
}

.customer-graph__detail {
  margin-top: var(--wm-space-3);
  padding: var(--wm-space-3) var(--wm-space-4);
  /* 节点要素浮层的 1px 边线（令牌纪律声明的极少数例外） */
  border: 1px solid var(--wm-border);
  border-radius: var(--wm-radius-md);
  background: var(--wm-bg-page);
}

.customer-graph__detail-head {
  display: flex;
  align-items: center;
  gap: var(--wm-space-2);
}

.customer-graph__detail-head h4 {
  margin: 0;
  color: var(--wm-text-primary);
}

.customer-graph__marked {
  color: var(--wm-color-danger);
  font-size: 0.85rem;
}

.customer-graph__detail dl {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--wm-space-1) var(--wm-space-3);
  margin: var(--wm-space-2) 0 0;
}

.customer-graph__detail dt {
  color: var(--wm-text-muted);
  font-size: 0.8rem;
}

.customer-graph__detail dd {
  margin: 0;
  font-size: 0.85rem;
  color: var(--wm-text-primary);
}
</style>
