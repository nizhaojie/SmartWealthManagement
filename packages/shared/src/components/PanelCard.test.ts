// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PanelCard from "./PanelCard.vue";

describe("PanelCard", () => {
  it("renders the title and the default slot content", () => {
    const wrapper = mount(PanelCard, {
      props: { title: "区块标题" },
      slots: { default: "<p data-testid='panel-content'>内容</p>" },
    });

    expect(wrapper.find('[data-testid="panel-card"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("区块标题");
    expect(wrapper.find('[data-testid="panel-content"]').exists()).toBe(true);
  });

  it("renders the actions slot next to the title", () => {
    const wrapper = mount(PanelCard, {
      props: { title: "区块标题" },
      slots: { actions: "<button data-testid='panel-action'>操作</button>" },
    });

    expect(wrapper.find('[data-testid="panel-action"]').exists()).toBe(true);
  });

  it("omits the actions container when the slot is not provided", () => {
    const wrapper = mount(PanelCard, { props: { title: "区块标题" } });

    expect(wrapper.find(".panel-card__actions").exists()).toBe(false);
  });
});
