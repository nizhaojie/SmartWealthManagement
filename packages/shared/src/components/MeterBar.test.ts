// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import MeterBar from "./MeterBar.vue";
import { ACCENTS } from "./accent";

const baseProps = { label: "样本比例", percent: 92 };

function fillWidth(percent: number): string | undefined {
  const wrapper = mount(MeterBar, { props: { label: "样本比例", percent } });
  return wrapper.get(".meter-bar__fill").attributes("style");
}

describe("MeterBar", () => {
  it("renders the label and the percent it was given", () => {
    const wrapper = mount(MeterBar, { props: baseProps });

    expect(wrapper.find('[data-testid="meter-bar"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("样本比例");
    expect(wrapper.text()).toContain("92%");
  });

  it("drives the fill width from the percent instead of a fixed class", () => {
    expect(fillWidth(40)).toContain("width: 40%");
  });

  it("clamps a percent outside 0–100 so the fill never overflows the track", () => {
    expect(fillWidth(-5)).toContain("width: 0%");
    expect(fillWidth(140)).toContain("width: 100%");
  });

  it("exposes the percent to assistive technology as a progressbar", () => {
    const track = mount(MeterBar, { props: baseProps }).get(".meter-bar__track");

    expect(track.attributes("role")).toBe("progressbar");
    expect(track.attributes("aria-label")).toBe("样本比例");
    expect(track.attributes("aria-valuenow")).toBe("92");
  });

  it("defaults accent to primary", () => {
    const wrapper = mount(MeterBar, { props: baseProps });

    expect(wrapper.classes()).toContain("meter-bar--accent-primary");
  });

  it("constrains accent to the semantic enum and maps each value to its modifier class", () => {
    // 与 StatCard 共用一份枚举：裸色值在类型层面就通不过，这里钉住枚举的完整清单。
    for (const accent of ACCENTS) {
      const wrapper = mount(MeterBar, { props: { ...baseProps, accent } });
      expect(wrapper.classes()).toContain(`meter-bar--accent-${accent}`);
    }
  });
});
