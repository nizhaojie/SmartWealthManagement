// 持仓穿透的树形展开：可展开节点的「展开 / 收起」是一个按钮控件，
// 它必须与页面其他按钮同属一个控件族（el-button），不能是浏览器默认样式的原生 button。
import ElementPlus from "element-plus";
import { mount, type VueWrapper } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import HoldingLookThrough from "./HoldingLookThrough.vue";
import type { LookThrough } from "./types";

function makeLookThrough(overrides: Partial<LookThrough> = {}): LookThrough {
  return {
    product_code: "F000001",
    product_name: "天枢货币基金",
    market_value: "20420.00",
    underlying_assets: [
      {
        asset_code: "CASH-0001",
        asset_name: "同业存单",
        asset_category: "现金",
        market_value: "20420.00",
        share: "1.0000",
        path_count: 1,
      },
    ],
    root: {
      kind: "product",
      code: "F000001",
      name: "天枢货币基金",
      depth: 1,
      share: "1.0000",
      market_value: "20420.00",
      asset_category: null,
      children: [
        {
          kind: "product",
          code: "F000009",
          name: "下层产品",
          depth: 2,
          share: "0.6000",
          market_value: "12252.00",
          asset_category: null,
          children: [
            {
              kind: "asset",
              code: "CASH-0001",
              name: "同业存单",
              depth: 3,
              share: "1.0000",
              market_value: "12252.00",
              asset_category: "现金",
              children: [],
            },
          ],
        },
        {
          kind: "asset",
          code: "CASH-0002",
          name: "7 天通知存款",
          depth: 2,
          share: "0.4000",
          market_value: "8168.00",
          asset_category: "现金",
          children: [],
        },
      ],
    },
    ...overrides,
  };
}

function mountPanel(lookThrough: LookThrough = makeLookThrough()): VueWrapper {
  return mount(HoldingLookThrough, {
    props: { lookThrough },
    global: { plugins: [ElementPlus] },
  });
}

describe("HoldingLookThrough", () => {
  it("renders each expandable node's toggle as an Element Plus button, like every other button on the page", () => {
    const panel = mountPanel();

    const toggles = panel.findAll('[data-testid="look-through-toggle"]');
    // 根节点默认展开：根与「下层产品」两处可展开，「同业存单」「7 天通知存款」是叶子。
    expect(toggles.length).toBeGreaterThan(0);
    for (const toggle of toggles) {
      expect(toggle.classes()).toContain("el-button");
      expect(toggle.classes()).toContain("el-button--small");
    }
  });

  it("expands and collapses one level at a time", async () => {
    const panel = mountPanel();

    const names = (): string[] =>
      panel.findAll('[data-testid="look-through-node-name"]').map((node) => node.text());
    expect(names()).toEqual(["天枢货币基金", "下层产品", "7 天通知存款"]);

    await panel.get('[data-testid="look-through-toggle"][data-code="F000009"]').trigger("click");
    expect(names()).toEqual(["天枢货币基金", "下层产品", "同业存单", "7 天通知存款"]);

    await panel.get('[data-testid="look-through-toggle"][data-code="F000009"]').trigger("click");
    expect(names()).toEqual(["天枢货币基金", "下层产品", "7 天通知存款"]);
  });
});
