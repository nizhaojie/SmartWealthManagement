// 图数据到渲染输入的转换：按关系类型过滤连带剔除失联节点、节点类型到
// packages/shared 分类色板序号的映射。业务命名（客户/产品/行业/基金经理）
// 留在这一层，shared 的图表壳只认泛化的 category 序号（ADR-0003）。

import type { GraphCategoryDatum, GraphEdgeDatum, GraphNodeDatum } from "@wealth/shared";
import type { GraphEdge, GraphEdgeType, GraphNode, GraphNodeType } from "./types";

export const NODE_TYPE_ORDER: readonly GraphNodeType[] = [
  "customer",
  "product",
  "industry",
  "fund_manager",
];

export const NODE_TYPE_LABELS: Record<GraphNodeType, string> = {
  customer: "客户",
  product: "产品",
  industry: "行业",
  fund_manager: "基金经理",
};

export const EDGE_TYPE_LABELS: Record<GraphEdgeType, string> = {
  HOLDS: "持有",
  BELONGS_TO_INDUSTRY: "所属行业",
  MANAGED_BY: "管理",
};

/**
 * 按勾选的关系类型过滤连线，再剔除因此失去全部连接的非客户节点——
 * 客户节点是这张图的锚点，即使暂时没有连线也保留，不然过滤到底会连
 * 空状态的判断依据（“图上还剩什么”）都没有了。
 */
export function filterAndPrune(
  nodes: readonly GraphNode[],
  edges: readonly GraphEdge[],
  activeEdgeTypes: readonly GraphEdgeType[],
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const activeTypes = new Set(activeEdgeTypes);
  const filteredEdges = edges.filter((edge) => activeTypes.has(edge.type));

  const connectedIds = new Set<string>();
  for (const edge of filteredEdges) {
    connectedIds.add(edge.source);
    connectedIds.add(edge.target);
  }

  const filteredNodes = nodes.filter(
    (node) => node.type === "customer" || connectedIds.has(node.id),
  );

  return { nodes: filteredNodes, edges: filteredEdges };
}

/** 把业务节点/连线映射成 shared 图表壳认得的泛化渲染输入。 */
export function toChartInput(
  nodes: readonly GraphNode[],
  edges: readonly GraphEdge[],
): { nodes: GraphNodeDatum[]; edges: GraphEdgeDatum[]; categories: GraphCategoryDatum[] } {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      name: node.label,
      category: NODE_TYPE_ORDER.indexOf(node.type),
      marked: node.marked,
    })),
    edges: edges.map((edge) => ({ source: edge.source, target: edge.target })),
    categories: NODE_TYPE_ORDER.map((type) => ({ name: NODE_TYPE_LABELS[type] })),
  };
}
