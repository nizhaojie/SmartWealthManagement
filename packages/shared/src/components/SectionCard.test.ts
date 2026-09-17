// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import SectionCard from "./SectionCard.vue";

describe("SectionCard", () => {
  it("renders the title and the default slot content", () => {
    const wrapper = mount(SectionCard, {
      props: { title: "区块标题" },
      slots: { default: "<p data-testid='section-content'>内容</p>" },
    });

    expect(wrapper.find('[data-testid="section-card"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("区块标题");
    expect(wrapper.find('[data-testid="section-content"]').exists()).toBe(true);
  });

  it("renders the actions slot next to the title", () => {
    const wrapper = mount(SectionCard, {
      props: { title: "区块标题" },
      slots: { actions: "<button data-testid='section-action'>操作</button>" },
    });

    expect(wrapper.find('[data-testid="section-action"]').exists()).toBe(true);
  });

  it("omits the actions container when the slot is not provided", () => {
    const wrapper = mount(SectionCard, { props: { title: "区块标题" } });

    expect(wrapper.find(".section-card__actions").exists()).toBe(false);
  });
});
