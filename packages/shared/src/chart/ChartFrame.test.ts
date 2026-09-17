// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toBarOption } from "./options";

// echarts 在 jsdom 里起不来也不必起来：壳的职责是状态机（加载/空/画），
// 用假实例把「画上去了吗」和「echarts 画了什么」分开。
const fakes = vi.hoisted(() => {
  type FakeInstance = {
    setOption: ReturnType<typeof vi.fn>;
    dispose: ReturnType<typeof vi.fn>;
    on: ReturnType<typeof vi.fn>;
    resize: ReturnType<typeof vi.fn>;
  };
  const instances: FakeInstance[] = [];
  return {
    instances,
    reset() {
      instances.length = 0;
    },
  };
});

vi.mock("./echarts", () => ({
  echarts: {
    init: () => {
      const instance = { setOption: vi.fn(), dispose: vi.fn(), on: vi.fn(), resize: vi.fn() };
      fakes.instances.push(instance);
      return instance;
    },
  },
}));

import ChartFrame from "./ChartFrame.vue";

const drawableOption = toBarOption([{ name: "甲", value: 1 }]);

describe("ChartFrame", () => {
  beforeEach(() => {
    fakes.reset();
  });

  it("renders title and hint when provided", () => {
    const wrapper = mount(ChartFrame, {
      props: { option: drawableOption, title: "图表标题", hint: "图表说明" },
    });

    expect(wrapper.find('[data-testid="chart-frame"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("图表标题");
    expect(wrapper.text()).toContain("图表说明");
  });

  it("shows the empty state with the default text when the option is null", () => {
    const wrapper = mount(ChartFrame, { props: { option: null } });

    expect(wrapper.find('[data-testid="chart-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="chart-empty"]').text()).toBe("暂无可展示的数据");
    expect(wrapper.find('[data-testid="chart-canvas"]').exists()).toBe(false);
    expect(fakes.instances).toHaveLength(0);
  });

  it("honors a custom emptyText", () => {
    const wrapper = mount(ChartFrame, { props: { option: null, emptyText: "暂无数据" } });

    expect(wrapper.find('[data-testid="chart-empty"]').text()).toBe("暂无数据");
  });

  it("shows the loading state instead of a canvas while loading, even with an option present", () => {
    const wrapper = mount(ChartFrame, { props: { option: drawableOption, loading: true } });

    expect(wrapper.find('[data-testid="chart-loading"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="chart-canvas"]').exists()).toBe(false);
    expect(fakes.instances).toHaveLength(0);
  });

  it("mounts an instance and passes the option through once an option is drawable", async () => {
    const wrapper = mount(ChartFrame, { props: { option: drawableOption } });

    await wrapper.vm.$nextTick();

    expect(wrapper.find('[data-testid="chart-canvas"]').exists()).toBe(true);
    expect(fakes.instances).toHaveLength(1);
    expect(fakes.instances[0]?.setOption).toHaveBeenCalledWith(drawableOption, true);
  });
});
