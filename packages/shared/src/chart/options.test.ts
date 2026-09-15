// 断言的是数据到图表配置的映射：类别顺序、系列数量、空数据处理。
// 像素输出不由这里负责。
//
// 夹具里的类别名刻意用无含义的字母：packages/shared 不允许承载业务语义
// （ADR-0003），连测试夹具里的「R1」「债券」也算是把业务词带进了这个包。

import { describe, expect, it } from "vitest";
import { CATEGORICAL_PALETTE, categoricalColorAt } from "./palette";
import { toBarOption, toDonutOption } from "./options";
import type { CategoryValue } from "./options";

const FIVE_CATEGORIES: CategoryValue[] = [
  { name: "A", value: 10000 },
  { name: "B", value: 2000 },
  { name: "C", value: 30000 },
  { name: "D", value: 0 },
  { name: "E", value: 500 },
];

describe("环图配置", () => {
  it("保留传入的类别顺序与数值", () => {
    const data: CategoryValue[] = [
      { name: "A", value: 60 },
      { name: "B", value: 30 },
      { name: "C", value: 10 },
    ];
    const option = toDonutOption(data);

    expect(option).not.toBeNull();
    const series = option?.series as { type: string; data: CategoryValue[] }[];
    expect(series).toHaveLength(1);
    expect(series[0].type).toBe("pie");
    expect(series[0].data.map((item) => item.name)).toEqual(["A", "B", "C"]);
    expect(series[0].data.map((item) => item.value)).toEqual([60, 30, 10]);
  });

  it("系列颜色取自分类色板，不取自 UI 主色", () => {
    const option = toDonutOption(FIVE_CATEGORIES);
    expect(option?.color).toEqual([...CATEGORICAL_PALETTE]);
  });

  it("没有可画的数值时返回 null，交给调用方渲染空状态", () => {
    expect(toDonutOption([])).toBeNull();
    expect(toDonutOption([{ name: "A", value: 0 }])).toBeNull();
  });
});

describe("横向条形图配置", () => {
  it("类别按传入顺序排列，不按数值大小重排", () => {
    const option = toBarOption(FIVE_CATEGORIES);

    expect(option).not.toBeNull();
    const yAxis = option?.yAxis as { type: string; inverse: boolean; data: string[] };
    const series = option?.series as { type: string; data: CategoryValue[] }[];

    expect(yAxis.type).toBe("category");
    expect(yAxis.data).toEqual(["A", "B", "C", "D", "E"]);
    expect(series).toHaveLength(1);
    expect(series[0].type).toBe("bar");
    expect(series[0].data.map((item) => item.value)).toEqual([10000, 2000, 30000, 0, 500]);
  });

  it("第一个类别落在顶部，读图顺序与类别顺序一致", () => {
    const option = toBarOption(FIVE_CATEGORIES);
    const yAxis = option?.yAxis as { inverse: boolean };
    expect(yAxis.inverse).toBe(true);
  });

  it("数值为零的类别也占一个位置，轴上的类别不因数值缺失而消失", () => {
    const option = toBarOption(FIVE_CATEGORIES);
    const series = option?.series as { data: CategoryValue[] }[];
    expect(series[0].data).toHaveLength(5);
    expect(series[0].data[3]).toMatchObject({ name: "D", value: 0 });
  });

  it("每个类别按序号取色，系列之间颜色不同", () => {
    const option = toBarOption(FIVE_CATEGORIES);
    const series = option?.series as {
      data: { itemStyle: { color: string } }[];
    }[];
    const colors = series[0].data.map((item) => item.itemStyle.color);

    expect(colors).toEqual(FIVE_CATEGORIES.map((_, index) => categoricalColorAt(index)));
    expect(new Set(colors).size).toBe(colors.length);
  });

  it("没有可画的数值时返回 null", () => {
    expect(toBarOption([])).toBeNull();
    expect(
      toBarOption([
        { name: "A", value: 0 },
        { name: "B", value: 0 },
      ]),
    ).toBeNull();
  });
});
