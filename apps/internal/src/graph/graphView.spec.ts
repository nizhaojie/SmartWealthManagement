// 断言的是图数据到渲染输入的转换：按关系类型过滤后连带剔除失去连接的节点、
// 节点类型到分类色板序号的映射。像素与力导向布局不由这里负责（那是
// packages/shared 的 toGraphOption）。

import { describe, expect, it } from "vitest";
import { filterAndPrune, NODE_TYPE_LABELS, NODE_TYPE_ORDER, toChartInput } from "./graphView";
import type { GraphEdge, GraphNode } from "./types";

function makeNode(overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "product:F000001",
    type: "product",
    label: "天枢货币基金",
    attrs: {},
    marked: false,
    ...overrides,
  };
}

const CUSTOMER = makeNode({ id: "customer:1", type: "customer", label: "王守成" });
const PRODUCT = makeNode({ id: "product:F000001", type: "product", label: "天枢货币基金" });
const INDUSTRY = makeNode({ id: "industry:大盘蓝筹", type: "industry", label: "大盘蓝筹" });
const FUND_MANAGER = makeNode({ id: "fund_manager:邵行", type: "fund_manager", label: "邵行" });

const HOLDS: GraphEdge = { source: "customer:1", target: "product:F000001", type: "HOLDS" };
const BELONGS_TO_INDUSTRY: GraphEdge = {
  source: "product:F000001",
  target: "industry:大盘蓝筹",
  type: "BELONGS_TO_INDUSTRY",
};
const MANAGED_BY: GraphEdge = {
  source: "product:F000001",
  target: "fund_manager:邵行",
  type: "MANAGED_BY",
};

const ALL_NODES = [CUSTOMER, PRODUCT, INDUSTRY, FUND_MANAGER];
const ALL_EDGES = [HOLDS, BELONGS_TO_INDUSTRY, MANAGED_BY];

describe("按关系类型过滤并剔除失联节点", () => {
  it("全部关系类型勾选时节点与连线原样保留", () => {
    const result = filterAndPrune(ALL_NODES, ALL_EDGES, ["HOLDS", "BELONGS_TO_INDUSTRY", "MANAGED_BY"]);
    expect(result.edges).toEqual(ALL_EDGES);
    expect(result.nodes.map((node) => node.id)).toEqual(ALL_NODES.map((node) => node.id));
  });

  it("只勾选一种关系类型时，另外两类关系连带的节点被剔除", () => {
    const result = filterAndPrune(ALL_NODES, ALL_EDGES, ["HOLDS"]);
    expect(result.edges).toEqual([HOLDS]);
    expect(result.nodes.map((node) => node.id)).toEqual(["customer:1", "product:F000001"]);
  });

  it("不勾选任何关系类型时只剩客户节点，连线清空", () => {
    const result = filterAndPrune(ALL_NODES, ALL_EDGES, []);
    expect(result.edges).toEqual([]);
    expect(result.nodes.map((node) => node.id)).toEqual(["customer:1"]);
  });

  it("客户节点永远保留，即使没有任何连线指向它", () => {
    const result = filterAndPrune([CUSTOMER], [], ["HOLDS"]);
    expect(result.nodes).toEqual([CUSTOMER]);
  });
});

describe("图数据到渲染输入的映射", () => {
  it("节点类型按固定顺序映射到分类色板序号，与节点列表顺序无关", () => {
    const input = toChartInput([FUND_MANAGER, INDUSTRY, CUSTOMER, PRODUCT], ALL_EDGES);
    const categoryById = Object.fromEntries(input.nodes.map((node) => [node.id, node.category]));

    expect(categoryById["customer:1"]).toBe(NODE_TYPE_ORDER.indexOf("customer"));
    expect(categoryById["product:F000001"]).toBe(NODE_TYPE_ORDER.indexOf("product"));
    expect(categoryById["industry:大盘蓝筹"]).toBe(NODE_TYPE_ORDER.indexOf("industry"));
    expect(categoryById["fund_manager:邵行"]).toBe(NODE_TYPE_ORDER.indexOf("fund_manager"));
  });

  it("类别顺序固定为四类节点在既定顺序里的中文图例", () => {
    const input = toChartInput(ALL_NODES, ALL_EDGES);
    expect(input.categories.map((category) => category.name)).toEqual(
      NODE_TYPE_ORDER.map((type) => NODE_TYPE_LABELS[type]),
    );
  });

  it("marked 与 name 原样透传给渲染输入", () => {
    const input = toChartInput([INDUSTRY], []);
    expect(input.nodes[0]).toMatchObject({ id: "industry:大盘蓝筹", name: "大盘蓝筹", marked: false });

    const markedInput = toChartInput([{ ...INDUSTRY, marked: true }], []);
    expect(markedInput.nodes[0].marked).toBe(true);
  });

  it("连线原样映射为渲染输入的 source/target", () => {
    const input = toChartInput(ALL_NODES, [HOLDS]);
    expect(input.edges).toEqual([{ source: "customer:1", target: "product:F000001" }]);
  });
});
