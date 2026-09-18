<script setup lang="ts">
// 持仓穿透：沿产品的底层持有关系逐层展开，让客户看清自己实际间接持有了什么。
// 同一底层资产的多条路径由后端合并，这里只负责呈现。
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
  <section class="look-through" data-testid="look-through-panel">
    <h3 class="look-through__title">持仓穿透 · {{ lookThrough.product_name }}</h3>
    <p class="look-through__hint">
      持仓市值 {{ lookThrough.market_value }} 元，按产品的底层持有关系逐层展开后分摊到下列底层资产。
      同一底层资产的多条路径已经合并。
    </p>

    <h4 class="look-through__subtitle">穿透后实际持有的底层资产</h4>
    <table class="look-through__table" data-testid="look-through-summary">
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

    <h4 class="look-through__subtitle">逐层展开</h4>
    <ul class="look-through__tree" data-testid="look-through-tree">
      <li
        v-for="row in rows"
        :key="row.key"
        class="look-through__node"
        data-testid="look-through-node"
        :data-code="row.node.code"
        :style="{ paddingLeft: `calc(var(--wm-space-4) * ${row.level})` }"
      >
        <el-button
          v-if="row.node.children.length > 0"
          size="small"
          class="look-through__toggle"
          data-testid="look-through-toggle"
          :data-code="row.node.code"
          :aria-expanded="isExpanded(row.key)"
          @click="toggle(row.key)"
        >
          {{ isExpanded(row.key) ? "收起" : "展开" }}
        </el-button>
        <span v-else class="look-through__leaf" aria-hidden="true">·</span>

        <span class="look-through__name" data-testid="look-through-node-name">{{ row.node.name }}</span>
        <span class="look-through__meta">{{ row.node.code }}</span>
        <span class="look-through__meta">第 {{ row.node.depth }} 层</span>
        <span class="look-through__meta">{{ percent(row.node.share) }}</span>
        <span class="look-through__meta">{{ row.node.market_value }} 元</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.look-through {
  padding: var(--wm-space-4);
  border: 1px solid var(--wm-border-hairline);
  border-radius: var(--wm-radius-md);
  background-color: var(--wm-bg-subtle);
}

.look-through__title {
  margin: 0;
  color: var(--wm-text-primary);
  font-size: 0.95rem;
  font-weight: 600;
}

.look-through__subtitle {
  margin: var(--wm-space-4) 0 var(--wm-space-2);
  color: var(--wm-text-primary);
  font-size: 0.9rem;
  font-weight: 600;
}

.look-through__hint {
  margin: var(--wm-space-1) 0 0;
  color: var(--wm-text-muted);
  font-size: 0.85rem;
  line-height: 1.75;
}

.look-through__table {
  width: 100%;
  border-collapse: collapse;
}

.look-through__table th,
.look-through__table td {
  padding: var(--wm-space-1) var(--wm-space-2);
  /* 表格行的 1px 分隔细线（令牌纪律声明的极少数例外） */
  border-bottom: 1px solid var(--wm-border-hairline);
  text-align: left;
  font-size: 0.85rem;
  white-space: nowrap;
}

.look-through__table th {
  color: var(--wm-text-muted);
  font-weight: 600;
}

.look-through__tree {
  margin: 0;
  padding: 0;
  list-style: none;
}

.look-through__node {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--wm-space-2);
  padding: var(--wm-space-1) 0;
  font-size: 0.85rem;
}

/* 与叶子节点的占位符同宽，深浅两层的名称因此能对齐成一列 */
.look-through__toggle {
  min-width: calc(var(--wm-space-6) * 1.5);
}

.look-through__leaf {
  display: inline-block;
  min-width: calc(var(--wm-space-6) * 1.5);
  color: var(--wm-text-placeholder);
  text-align: center;
}

.look-through__name {
  color: var(--wm-text-primary);
  font-weight: 600;
}

.look-through__meta {
  color: var(--wm-text-muted);
  font-variant-numeric: tabular-nums;
}
</style>
