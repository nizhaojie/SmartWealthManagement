// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { defineComponent, nextTick } from "vue";
import { describe, expect, it } from "vitest";
import AppShell from "./AppShell.vue";
import type { AppShellNavItem } from "./nav";

const StubIcon = defineComponent({
  name: "StubIcon",
  template: "<svg data-testid='stub-icon' />",
});

const navItems: AppShellNavItem[] = [
  { key: "home", label: "首页", name: "nav-home", icon: StubIcon },
  { key: "settings", label: "设置" },
];

function mountShell(
  props: { activeKey?: string; brandSubtitle?: string } = {},
  slots: Record<string, string> = {},
) {
  return mount(AppShell, {
    props: { navItems, ...props },
    slots: {
      brand: "<b>某系统</b>",
      "topbar-left": "<div data-testid='topbar-left-slot' />",
      "topbar-right": "<span data-testid='topbar-right-slot'>某人</span>",
      default: "<div data-testid='content-slot' />",
      ...slots,
    },
  });
}

describe("AppShell", () => {
  it("renders one nav entry per item with its label and anchor name", () => {
    const wrapper = mountShell();

    const home = wrapper.find('button[name="nav-home"]');
    expect(home.exists()).toBe(true);
    expect(home.text()).toContain("首页");
    expect(wrapper.text()).toContain("设置");
  });

  it("renders the icon of a nav entry when provided", () => {
    const wrapper = mountShell();

    expect(wrapper.find('[data-testid="stub-icon"]').exists()).toBe(true);
  });

  it("marks only the active nav entry and emits select with its key on click", async () => {
    const wrapper = mountShell({ activeKey: "settings" });

    const entries = wrapper.findAll(".app-shell__nav-item");
    expect(entries[0].attributes("aria-current")).toBeUndefined();
    expect(entries[1].attributes("aria-current")).toBe("page");

    await entries[0].trigger("click");
    expect(wrapper.emitted("select")).toEqual([["home"]]);
  });

  it("renders the badge of a nav entry without interpreting it", () => {
    const wrapper = mount(AppShell, {
      props: { navItems: [{ key: "alerts", label: "风控", badge: 3 }, { key: "plain", label: "无徽标" }] },
    });

    const badges = wrapper.findAll(".app-shell__nav-badge");
    expect(badges).toHaveLength(1);
    expect(badges[0].text()).toBe("3");
  });

  it("always renders the logout entry and emits logout on click", async () => {
    const wrapper = mountShell();

    const logout = wrapper.find('button[name="logout"]');
    expect(logout.exists()).toBe(true);
    await logout.trigger("click");
    expect(wrapper.emitted("logout")).toHaveLength(1);
  });

  it("keeps the logout entry rendered for an empty navigation", () => {
    const wrapper = mount(AppShell, { props: { navItems: [] } });

    expect(wrapper.find('button[name="logout"]').exists()).toBe(true);
  });

  it("renders every named slot, including the optional sidebar footer", async () => {
    const wrapper = mountShell(
      { brandSubtitle: "Copilot" },
      { "sidebar-footer": "<div data-testid='sidebar-footer-slot' />" },
    );
    await nextTick();

    expect(wrapper.text()).toContain("某系统");
    expect(wrapper.text()).toContain("Copilot");
    expect(wrapper.find('[data-testid="topbar-left-slot"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="topbar-right-slot"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="content-slot"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="sidebar-footer-slot"]').exists()).toBe(true);
  });

  it("omits the sidebar footer container when the slot is not provided", () => {
    const wrapper = mountShell();

    expect(wrapper.find(".app-shell__sidebar-footer").exists()).toBe(false);
  });

  it("stays two-column when no inspector slot is provided", () => {
    const wrapper = mountShell();

    expect(wrapper.classes()).not.toContain("app-shell--with-inspector");
    expect(wrapper.find(".app-shell__inspector").exists()).toBe(false);
  });

  it("takes the three-column shape from the inspector slot alone, with no variant prop", () => {
    const wrapper = mountShell({}, { inspector: "<div data-testid='inspector-slot' />" });

    expect(wrapper.classes()).toContain("app-shell--with-inspector");
    expect(wrapper.find(".app-shell__inspector").exists()).toBe(true);
    expect(wrapper.find('[data-testid="inspector-slot"]').exists()).toBe(true);
  });
});
