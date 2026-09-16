export type GraphNodeType = "customer" | "product" | "industry" | "fund_manager";

export type GraphEdgeType = "HOLDS" | "BELONGS_TO_INDUSTRY" | "MANAGED_BY";

export type GraphNode = {
  id: string;
  type: GraphNodeType;
  label: string;
  attrs: Record<string, unknown>;
  marked: boolean;
};

export type GraphEdge = {
  source: string;
  target: string;
  type: GraphEdgeType;
};

export type CustomerGraphView = {
  customer_id: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  synced_at: string | null;
};
