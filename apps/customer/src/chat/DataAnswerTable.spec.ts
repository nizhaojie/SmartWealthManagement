// 结果表是数据回答里数字的唯一出处（ADR-0028）：表头走中文 label（英文列名不上界面）、
// 缺值统一「—」、截断常写常显、没有表时整件不渲染（不留空壳）。
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { DataAnswer } from "./api";
import DataAnswerTable from "./DataAnswerTable.vue";

function makeData(overrides: Partial<DataAnswer> = {}): DataAnswer {
  return {
    columns: [
      { key: "product_name", label: "产品名称" },
      { key: "market_value", label: "市值（元）" },
    ],
    rows: [
      ["稳健增利", 120000],
      ["天枢货币基金", null],
    ],
    row_count: 2,
    truncated: false,
    views: ["持仓明细"],
    ...overrides,
  };
}

describe("DataAnswerTable", () => {
  it("表头取中文 label，行按列顺序铺开", () => {
    const wrapper = mount(DataAnswerTable, { props: { data: makeData() } });

    const headers = wrapper.findAll("thead th").map((th) => th.text());
    expect(headers).toEqual(["产品名称", "市值（元）"]);

    const rows = wrapper.findAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0].findAll("td").map((td) => td.text())).toEqual(["稳健增利", "120000"]);
    // 英文列名只用来定位值，一个字都不该出现在界面上。
    expect(wrapper.text()).not.toContain("product_name");
  });

  it("缺值渲染成「—」，不是空白也不是 0", () => {
    const wrapper = mount(DataAnswerTable, { props: { data: makeData() } });

    const secondRow = wrapper.findAll("tbody tr")[1];
    expect(secondRow.findAll("td")[1].text()).toBe("—");
  });

  it("行数常写常显；截断时另给一句提示", () => {
    const wrapper = mount(DataAnswerTable, {
      props: { data: makeData({ truncated: true, row_count: 200 }) },
    });

    expect(wrapper.get('[data-testid="data-answer-count"]').text()).toContain("共 200 行");
    const notice = wrapper.get('[data-testid="data-answer-truncation"]');
    expect(notice.text()).toContain("仅显示前 200 行");
  });

  it("没被截断时不出现截断提示", () => {
    const wrapper = mount(DataAnswerTable, { props: { data: makeData() } });

    expect(wrapper.find('[data-testid="data-answer-truncation"]').exists()).toBe(false);
  });

  it("没有结果表时整件不渲染：零行 / 失败 / 白名单外都不留空壳", () => {
    const noTable = mount(DataAnswerTable, { props: { data: null } });
    expect(noTable.find('[data-testid="data-answer"]').exists()).toBe(false);
    expect(noTable.find('[data-testid="data-answer-table"]').exists()).toBe(false);

    // 气泡里没带这个字段时传的是 undefined，同样不该冒出一张空表。
    const absent = mount(DataAnswerTable);
    expect(absent.find(".table-wrap").exists()).toBe(false);
  });
});
