// 客户可见视图的边界：结果页只呈现等级结论与呈现文案，
// 内部的研判结论与置信度不出现在客户侧。
import ElementPlus from "element-plus";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ResultPage from "./ResultPage.vue";

describe("ResultPage", () => {
  it("explains the risk tolerance grade in Chinese and shows the validity date", () => {
    const wrapper = mount(ResultPage, {
      global: { plugins: [ElementPlus] },
      props: {
        result: { risk_level: "C3", valid_until: "2027-09-15" },
      },
    });

    const text = wrapper.text();
    expect(text).toContain("C3");
    expect(text).toContain("平衡型");
    expect(text).toContain("2027-09-15");
    expect(text).toContain("收益与波动取得平衡");
    expect(text).not.toContain("置信度");
    expect(text).not.toContain("研判");
  });
});
