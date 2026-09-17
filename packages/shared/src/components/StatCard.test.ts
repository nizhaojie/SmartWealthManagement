// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import StatCard from "./StatCard.vue";
import { STAT_CARD_ACCENTS } from "./statCard";

const baseProps = { title: "样本指标", value: "12,800.00" };

describe("StatCard", () => {
  it("renders title and value", () => {
    const wrapper = mount(StatCard, { props: baseProps });

    expect(wrapper.text()).toContain("样本指标");
    expect(wrapper.text()).toContain("12,800.00");
  });

  it("accepts a numeric value as-is; formatting stays with the caller", () => {
    const wrapper = mount(StatCard, { props: { title: "样本指标", value: 1234.5 } });

    expect(wrapper.text()).toContain("1234.5");
  });

  it("omits the trend line when no trend is given", () => {
    const wrapper = mount(StatCard, { props: baseProps });

    expect(wrapper.find('[data-testid="stat-card-trend"]').exists()).toBe(false);
  });

  it("renders the trend label and marks its direction; the color decision stays inside the component", () => {
    const up = mount(StatCard, {
      props: { ...baseProps, trend: { direction: "up", label: "较上期 +12.4%" } },
    });
    const down = mount(StatCard, {
      props: { ...baseProps, trend: { direction: "down", label: "较上期 -3.1%" } },
    });

    const upTrend = up.find('[data-testid="stat-card-trend"]');
    expect(upTrend.classes()).toContain("stat-card__trend--up");
    expect(upTrend.text()).toContain("较上期 +12.4%");

    const downTrend = down.find('[data-testid="stat-card-trend"]');
    expect(downTrend.classes()).toContain("stat-card__trend--down");
    expect(downTrend.text()).toContain("较上期 -3.1%");
  });

  it("renders the icon slot", () => {
    const wrapper = mount(StatCard, {
      props: baseProps,
      slots: { icon: "<svg data-testid='stat-card-icon-slot' />" },
    });

    expect(wrapper.find('[data-testid="stat-card-icon-slot"]').exists()).toBe(true);
  });

  it("defaults accent to primary", () => {
    const wrapper = mount(StatCard, { props: baseProps });

    expect(wrapper.classes()).toContain("stat-card--accent-primary");
  });

  it("constrains accent to the semantic enum and maps each value to its modifier class", () => {
    // 裸色值（如 "#ff0000"）在类型层面就无法通过——StatCardAccent 只收这六个语义名，
    // 这里钉住枚举的完整清单，防止静默增删。
    expect([...STAT_CARD_ACCENTS]).toEqual([
      "primary",
      "up",
      "down",
      "success",
      "warning",
      "danger",
    ]);

    for (const accent of STAT_CARD_ACCENTS) {
      const wrapper = mount(StatCard, { props: { ...baseProps, accent } });
      expect(wrapper.classes()).toContain(`stat-card--accent-${accent}`);
    }
  });
});
