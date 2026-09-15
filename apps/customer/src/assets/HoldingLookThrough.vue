<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { LookThrough, LookThroughNode } from "./types";

const props = defineProps<{ lookThrough: LookThrough }>();

type Row = {
  key: string;
  node: LookThroughNode;
  level: number;
};

const expanded = ref<Set<string>>(new Set([props.lookThrough.root.code]));

watch(
  () => props.lookThrough.root.code,
  (rootCode) => {
    expanded.value = new Set([rootCode]);
  },
);

const rows = computed<Row[]>(() => {
  const visible: Row[] = [];
  const walk = (node: LookThroughNode, level: number, key: string) => {
    visible.push({ key, node, level });
    if (!expanded.value.has(key)) return;
    for (const child of node.children) {
      walk(child, level + 1, `${key} > ${child.code}`);
    }
  };
  walk(props.lookThrough.root, 0, props.lookThrough.root.code);
  return visible;
});

function isExpanded(key: string): boolean {
  return expanded.value.has(key);
}

function toggle(key: string): void {
  const next = new Set(expanded.value);
  if (next.has(key)) {
    next.delete(key);
  } else {
    next.add(key);
  }
  expanded.value = next;
}

function percent(share: string): string {
  return `${(Number(share) * 100).toFixed(2)}%`;
}
</script>

<template>
  <section data-testid="look-through-panel">
    <h3>持仓穿透 · {{ lookThrough.product_name }}</h3>
    <p class="hint">
      持仓市值 {{ lookThrough.market_value }} 元，按产品的底层持有关系逐层展开后分摊到下列底层资产。
      同一底层资产的多条路径已经合并。
    </p>

    <h4>穿透后实际持有的底层资产</h4>
    <table data-testid="look-through-summary">
      <thead>
        <tr>
          <th>底层资产</th>
          <th>资产大类</th>
          <th>市值（元）</th>
          <th>占比</th>
          <th>路径</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="asset in lookThrough.underlying_assets"
          :key="asset.asset_code"
          data-testid="look-through-asset"
          :data-asset-code="asset.asset_code"
        >
          <td>{{ asset.asset_name }}（{{ asset.asset_code }}）</td>
          <td>{{ asset.asset_category }}</td>
          <td>{{ asset.market_value }}</td>
          <td>{{ percent(asset.share) }}</td>
          <td>{{ asset.path_count }} 条</td>
        </tr>
      </tbody>
    </table>

    <h4>逐层展开</h4>
    <ul data-testid="look-through-tree">
      <li
        v-for="row in rows"
        :key="row.key"
        data-testid="look-through-node"
        :data-code="row.node.code"
        :style="{ paddingLeft: `${row.level * 1.25}rem` }"
      >
        <button
          v-if="row.node.children.length > 0"
          type="button"
          data-testid="look-through-toggle"
          :data-code="row.node.code"
          :aria-expanded="isExpanded(row.key)"
          @click="toggle(row.key)"
        >
          {{ isExpanded(row.key) ? "收起" : "展开" }}
        </button>
        <span v-else class="leaf" aria-hidden="true">·</span>

        <span data-testid="look-through-node-name">{{ row.node.name }}</span>
        <span>{{ row.node.code }}</span>
        <span>第 {{ row.node.depth }} 层</span>
        <span>{{ percent(row.node.share) }}</span>
        <span>{{ row.node.market_value }} 元</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.hint {
  margin: 0.25rem 0 0.75rem;
}

h3 {
  margin: 0;
  font-size: 1rem;
}

h4 {
  margin: 1rem 0 0.5rem;
  font-size: 0.95rem;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  text-align: left;
  padding: 0.35rem 0.6rem;
  border-bottom: 1px solid var(--el-border-color-lighter);
  white-space: nowrap;
}

ul {
  list-style: none;
  margin: 0;
  padding: 0;
}

li {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: baseline;
  padding: 0.25rem 0;
}

button {
  min-width: 3.25rem;
}

.leaf {
  display: inline-block;
  min-width: 3.25rem;
  text-align: center;
}
</style>
